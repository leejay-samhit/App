import { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TextInput,
  TouchableOpacity,
  ScrollView,
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";

type Category = {
  id: string;
  name: string;
  slug: string;
  icon: string;
  color: string;
  active: boolean;
  provider_count: number;
};

const LANG_OPTIONS = [
  { code: "en", label: "English" },
  { code: "te", label: "Telugu" },
  { code: "hi", label: "Hindi" },
  { code: "ta", label: "Tamil" },
];

export default function ServiceApply() {
  const router = useRouter();
  const [serviceName, setServiceName] = useState("");
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [categoryName, setCategoryName] = useState("");
  const [categories, setCategories] = useState<Category[]>([]);
  // June 2026 — sub-category support
  const [subcategoryId, setSubcategoryId] = useState<string | null>(null);
  const [subcategoryName, setSubcategoryName] = useState<string>("");
  const [subcategories, setSubcategories] = useState<{ id: string; name: string; icon?: string }[]>([]);
  const [pincode, setPincode] = useState("");
  const [description, setDescription] = useState("");
  const [languages, setLanguages] = useState<string[]>([]);
  const [acceptTerms, setAcceptTerms] = useState(false);
  const [revealCfg, setRevealCfg] = useState<{ fee: number; total: number; gst_pct: number } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [existing, setExisting] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [registrationPaid, setRegistrationPaid] = useState<boolean | null>(null);
  const [approvalStatus, setApprovalStatus] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        // load categories first
        const c = await api.get<{ categories: Category[] }>("/services/categories");
        setCategories(c.data.categories || []);
        // Reveal fee config for the T&C banner
        try {
          const rc = await api.get("/services/reveal-config");
          setRevealCfg({ fee: rc.data.fee, total: rc.data.total, gst_pct: rc.data.gst_pct });
        } catch {}
        // also check registration / approval status — apply requires both
        const me = await api.get<any>("/auth/me");
        setRegistrationPaid(!!me.data?.registration_paid);
        setApprovalStatus(me.data?.approval_status || null);
        const { data } = await api.get("/service/me");
        setExisting(data);
        if (data?.application) {
          setServiceName(data.application.service_name || "");
          setCategoryName(data.application.service_category || "");
          setCategoryId(data.application.category_id || null);
          setSubcategoryId(data.application.service_subcategory_id || null);
          setSubcategoryName(data.application.service_subcategory_name || "");
          setPincode(data.application.pincode || "");
          setCharge(String(data.application.charge || ""));
          setDescription(data.application.description || "");
          setLanguages(data.application.languages || []);
        }
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const toggleLanguage = (code: string) => {
    setLanguages((prev) => (prev.includes(code) ? prev.filter((x) => x !== code) : [...prev, code]));
  };

  // Whenever the user picks a different parent category, fetch its
  // sub-categories. We DON'T reset subcategoryId here on initial load so
  // the form correctly hydrates from an existing pending application.
  useEffect(() => {
    if (!categoryId) {
      setSubcategories([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get<{ items: { id: string; name: string; icon?: string }[] }>(
          `/service-subcategories?parent_id=${encodeURIComponent(categoryId)}`,
        );
        if (!cancelled) setSubcategories(r.data.items || []);
      } catch {
        if (!cancelled) setSubcategories([]);
      }
    })();
    return () => { cancelled = true; };
  }, [categoryId]);

  const showError = (msg: string) => {
    setFormError(msg);
    Alert.alert("Heads up", msg);
  };

  const submit = async () => {
    setFormError(null);
    if (!serviceName.trim() || serviceName.trim().length < 2)
      return showError("Please enter a service name (at least 2 characters).");
    if (!categoryId)
      return showError("Please pick a category from the list.");
    if (!/^\d{6}$/.test(pincode))
      return showError("Pincode must be 6 digits.");
    if (languages.length === 0)
      return showError("Pick at least one language you can speak with customers.");
    if (!acceptTerms)
      return showError("Please tick the terms & conditions checkbox to continue.");
    setSubmitting(true);
    try {
      await api.post("/service/apply", {
        service_name: serviceName.trim(),
        service_category: categoryName,
        category_id: categoryId,
        service_subcategory_id: subcategoryId,
        pincode,
        // Charge is no longer collected from the provider — the platform
        // monetises via the customer-side phone-reveal fee. Backend still
        // expects a positive number, so we send 1 as a placeholder.
        charge: 1,
        description: description.trim() || null,
        languages,
      });
      Alert.alert("Submitted", "Your service application is under review.", [
        { text: "OK", onPress: () => router.back() },
      ]);
    } catch (e) {
      const msg = formatApiError(e);
      setFormError(msg);
      Alert.alert("Could not submit", msg);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading)
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      </SafeAreaView>
    );

  const status = existing?.service_status as string | null;
  const isApproved = status === "approved";
  const isPending = status === "pending";
  const needsRegistration = registrationPaid === false;
  const locked = isApproved || isPending || needsRegistration;
  const banner = needsRegistration
    ? {
        color: colors.error,
        label: "Pay your ₹100 registration fee first to list a service.",
        cta: { text: "Pay now", route: "/payment" },
      }
    : isApproved
    ? { color: colors.success, label: "You're a verified service provider" }
    : isPending
    ? { color: colors.accent, label: "Application under review" }
    : status === "rejected"
    ? { color: colors.error, label: existing?.application?.reject_reason || "Last application rejected — try again" }
    : null;

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
          <View style={styles.header}>
            <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}>
              <Feather name="arrow-left" size={20} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.title}>List your service</Text>
          </View>

          {banner && (
            <View style={[styles.banner, { backgroundColor: banner.color + "22", borderColor: banner.color }]}>
              <Feather name={isApproved ? "check-circle" : isPending ? "clock" : "alert-circle"} size={16} color={banner.color} />
              <Text style={[styles.bannerText, { color: banner.color }]} numberOfLines={3}>{banner.label}</Text>
              {(banner as any).cta ? (
                <TouchableOpacity
                  onPress={() => router.push((banner as any).cta.route)}
                  style={[styles.bannerCta, { backgroundColor: banner.color }]}
                >
                  <Text style={styles.bannerCtaText}>{(banner as any).cta.text}</Text>
                </TouchableOpacity>
              ) : null}
            </View>
          )}

          {formError ? (
            <View style={styles.inlineError}>
              <Feather name="alert-triangle" size={14} color={colors.error} />
              <Text style={styles.inlineErrorText} numberOfLines={3}>  {formError}</Text>
            </View>
          ) : null}

          <Text style={styles.label}>Service name</Text>
          <TextInput
            style={styles.input}
            value={serviceName}
            onChangeText={setServiceName}
            placeholder="e.g. AC Installation & Repair"
            placeholderTextColor={colors.textMuted}
            editable={!locked}
          />

          <Text style={styles.label}>Category</Text>
          <View style={styles.catGrid}>
            {categories.map((c) => {
              const sel = categoryId === c.id;
              return (
                <TouchableOpacity
                  key={c.id}
                  disabled={locked}
                  onPress={() => {
                    if (c.id !== categoryId) {
                      // New category picked — clear stale sub-category selection
                      setSubcategoryId(null);
                      setSubcategoryName("");
                    }
                    setCategoryId(c.id);
                    setCategoryName(c.name);
                  }}
                  style={[
                    styles.catTile,
                    sel ? { borderColor: c.color, backgroundColor: c.color + "15" } : null,
                    locked ? { opacity: 0.55 } : null,
                  ]}
                >
                  <View style={[styles.catIconWrap, { backgroundColor: c.color + "20" }]}>
                    <Feather name={c.icon as any} size={20} color={c.color} />
                  </View>
                  <Text style={styles.catTileText} numberOfLines={2}>{c.name}</Text>
                </TouchableOpacity>
              );
            })}
          </View>

          {/* June 2026 — Sub-category picker. Only shown when the chosen
              parent category has sub-categories configured by the admin.
              Optional: users can skip if no specific sub-category matches. */}
          {categoryId && subcategories.length > 0 ? (
            <>
              <Text style={styles.label}>Sub-category <Text style={{ color: colors.textMuted, fontWeight: "600" }}>(optional)</Text></Text>
              <View style={styles.langRow}>
                <TouchableOpacity
                  disabled={locked}
                  onPress={() => { setSubcategoryId(null); setSubcategoryName(""); }}
                  style={[
                    styles.langChip,
                    subcategoryId === null && styles.langChipActive,
                    locked && { opacity: 0.55 },
                  ]}
                >
                  <Text style={[styles.langChipText, subcategoryId === null && styles.langChipTextActive]}>
                    Any / general
                  </Text>
                </TouchableOpacity>
                {subcategories.map((s) => {
                  const sel = subcategoryId === s.id;
                  return (
                    <TouchableOpacity
                      key={s.id}
                      disabled={locked}
                      onPress={() => { setSubcategoryId(s.id); setSubcategoryName(s.name); }}
                      style={[styles.langChip, sel && styles.langChipActive, locked && { opacity: 0.55 }]}
                      testID={`apply-subcat-${s.id}`}
                    >
                      {sel ? <Feather name="check" size={12} color={colors.primaryFg} /> : null}
                      {s.icon && !sel ? <Feather name={s.icon as any} size={12} color={colors.textMain} /> : null}
                      <Text style={[styles.langChipText, sel && styles.langChipTextActive]}>
                        {(sel || s.icon) ? "  " : ""}{s.name}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
            </>
          ) : null}

          <Text style={styles.label}>Languages you speak</Text>
          <View style={styles.langRow}>
            {LANG_OPTIONS.map((l) => {
              const sel = languages.includes(l.code);
              return (
                <TouchableOpacity
                  key={l.code}
                  disabled={locked}
                  onPress={() => toggleLanguage(l.code)}
                  style={[styles.langChip, sel && styles.langChipActive, locked && { opacity: 0.55 }]}
                >
                  {sel ? <Feather name="check" size={12} color={colors.primaryFg} /> : null}
                  <Text style={[styles.langChipText, sel && styles.langChipTextActive]}>{l.label}</Text>
                </TouchableOpacity>
              );
            })}
          </View>

          <Text style={styles.label}>Pincode</Text>
          <TextInput
            style={styles.input}
            value={pincode}
            onChangeText={setPincode}
            placeholder="6 digits"
            placeholderTextColor={colors.textMuted}
            keyboardType="numeric"
            maxLength={6}
            editable={!locked}
          />

          {/* Phone-reveal model — replaces the old "charge per booking" field.
              Customers pay a small platform fee to unlock the provider's number;
              the provider keeps 100% of whatever they earn off-platform. */}
          <View style={styles.tncCard}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Feather name="info" size={16} color={colors.primary} />
              <Text style={styles.tncTitle}>How it works</Text>
            </View>
            <Text style={styles.tncBody}>
              When a customer wants to call you, the app collects{" "}
              <Text style={{ fontWeight: "800", color: colors.textMain }}>
                {revealCfg
                  ? `₹${revealCfg.total.toFixed(2)} (₹${revealCfg.fee.toFixed(2)} fee + ${revealCfg.gst_pct.toFixed(0)}% GST)`
                  : "₹1 + 18% GST"}
              </Text>{" "}
              from them to reveal your phone number. You keep{" "}
              <Text style={{ fontWeight: "800", color: colors.success }}>100%</Text> of whatever
              you charge the customer directly after that. There's no booking fee or commission
              on your earnings.
            </Text>
            <TouchableOpacity
              onPress={() => setAcceptTerms((v) => !v)}
              style={styles.tncCheckRow}
              testID="apply-tnc-checkbox"
              disabled={locked}
            >
              <View style={[styles.tncCheckBox, acceptTerms && styles.tncCheckBoxOn]}>
                {acceptTerms ? <Feather name="check" size={13} color="#fff" /> : null}
              </View>
              <Text style={styles.tncCheckText}>
                I agree to the{" "}
                <Text style={{ fontWeight: "800", color: colors.primary }}>terms & conditions</Text>
                : customer pays ₹1 to my profile to reveal my number; I provide my service privately.
              </Text>
            </TouchableOpacity>
          </View>

          <Text style={styles.label}>Description (optional)</Text>
          <TextInput
            style={[styles.input, { minHeight: 90, textAlignVertical: "top" }]}
            value={description}
            onChangeText={setDescription}
            placeholder="What you offer, experience, area covered..."
            placeholderTextColor={colors.textMuted}
            multiline
            maxLength={500}
            editable={!locked}
          />

          {!locked && (
            <TouchableOpacity
              style={[styles.submitBtn, submitting && { opacity: 0.6 }]}
              onPress={submit}
              disabled={submitting}
            >
              {submitting ? (
                <ActivityIndicator color={colors.primaryFg} />
              ) : (
                <Text style={styles.submitText}>Submit application</Text>
              )}
            </TouchableOpacity>
          )}

          {isApproved ? (
            <TouchableOpacity
              style={styles.locManageBtn}
              onPress={() => router.push("/services/location" as any)}
            >
              <Feather name="navigation" size={16} color={colors.primary} />
              <Text style={styles.locManageBtnText}>  Manage Live Location (nearby workers)</Text>
              <Feather name="chevron-right" size={16} color={colors.primary} style={{ marginLeft: "auto" }} />
            </TouchableOpacity>
          ) : null}

          <Text style={styles.help}>
            Once approved by admin, you’ll appear in the Services directory in the user’s pincode area. Earnings credit to your wallet (minus a small platform fee).
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { padding: spacing.screen, paddingBottom: 60 },
  header: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 20 },
  backBtn: {
    width: 38, height: 38, borderRadius: 19,
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  title: { fontSize: 22, fontWeight: "800", color: colors.textMain },
  banner: {
    flexDirection: "row", alignItems: "center", gap: 8,
    padding: 10, borderRadius: 10, borderWidth: 1, marginBottom: 14,
  },
  bannerText: { fontSize: 12, fontWeight: "700", flex: 1, lineHeight: 16 },
  bannerCta: {
    paddingVertical: 6, paddingHorizontal: 10,
    borderRadius: 6,
  },
  bannerCtaText: { color: "#fff", fontSize: 11, fontWeight: "800" },
  inlineError: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: colors.error + "15",
    borderWidth: 1, borderColor: colors.error + "55",
    borderRadius: 10, padding: 10,
    marginBottom: 12,
  },
  inlineErrorText: { color: colors.error, fontSize: 12, fontWeight: "700", flex: 1 },
  label: {
    fontSize: 12, fontWeight: "700", color: colors.textMuted,
    marginTop: 14, marginBottom: 8, letterSpacing: 0.6,
  },
  input: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 12, paddingHorizontal: 14, paddingVertical: 12,
    fontSize: 14, color: colors.textMain,
  },
  catGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  catTile: {
    width: "31.5%", aspectRatio: 1,
    backgroundColor: colors.surface,
    borderRadius: 12, borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
    padding: 8,
  },
  catIconWrap: {
    width: 38, height: 38, borderRadius: 10,
    alignItems: "center", justifyContent: "center", marginBottom: 6,
  },
  catTileText: { fontSize: 10.5, fontWeight: "700", color: colors.textMain, textAlign: "center", lineHeight: 13 },
  langRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  langChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingVertical: 8, paddingHorizontal: 14, borderRadius: 999,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  langChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  langChipText: { fontSize: 12, fontWeight: "700", color: colors.textMuted },
  langChipTextActive: { color: colors.primaryFg },
  submitBtn: {
    marginTop: 22, backgroundColor: colors.primary,
    borderRadius: radii.button, paddingVertical: 14, alignItems: "center",
  },
  submitText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  locManageBtn: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 13, paddingHorizontal: 14,
    borderRadius: radii.button,
    backgroundColor: colors.primary + "12",
    borderWidth: 1, borderColor: colors.primary + "33",
    marginTop: 14,
  },
  locManageBtnText: { color: colors.primary, fontWeight: "700", fontSize: 13 },
  help: { fontSize: 11, color: colors.textMuted, marginTop: 16, lineHeight: 16 },
  // Phone-reveal model T&C card
  tncCard: {
    marginTop: 18,
    padding: 14,
    borderRadius: 14,
    backgroundColor: colors.primary + "0A",
    borderWidth: 1,
    borderColor: colors.primary + "33",
  },
  tncTitle: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  tncBody: { fontSize: 12, color: colors.textMain, marginTop: 8, lineHeight: 18 },
  tncCheckRow: { flexDirection: "row", alignItems: "flex-start", gap: 10, marginTop: 12 },
  tncCheckBox: {
    width: 22, height: 22, borderRadius: 6,
    borderWidth: 2, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
    marginTop: 1,
  },
  tncCheckBoxOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  tncCheckText: { flex: 1, fontSize: 12, color: colors.textMuted, lineHeight: 18 },
});
