// Admin AI Tools — generate text (descriptions / marketing / titles) and
// images (category icons, banners) via the Emergent LLM Key. Admin pastes
// the output back into the relevant category / service form. Decoupling
// the AI panel keeps the existing CRUD UIs simple while still offering
// the AI lift the user asked for.
import { useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  TextInput, ActivityIndicator, Alert, Image, Platform,
  KeyboardAvoidingView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import { useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing } from "../../src/theme";
import { useTabSwipe } from "../../src/use-swipe-pager";

type Kind = "service_description" | "category_description" | "marketing" | "service_title" | "improve";
const KINDS: { k: Kind; label: string; hint: string }[] = [
  { k: "service_description",  label: "Service description",  hint: "e.g. \"experienced plumber, 5 years\"" },
  { k: "category_description", label: "Category description", hint: "e.g. \"home electrical services\"" },
  { k: "marketing",            label: "Marketing copy",       hint: "e.g. \"sale on AC repair\"" },
  { k: "service_title",        label: "Service title",        hint: "e.g. \"AC servicing\"" },
  { k: "improve",              label: "Improve existing text", hint: "paste original text in the 'Existing' box" },
];

type ImgStyle = "flat-icon" | "banner" | "illustration" | "hero";
const IMG_STYLES: { k: ImgStyle; label: string }[] = [
  { k: "flat-icon",    label: "Flat icon" },
  { k: "illustration", label: "Illustration" },
  { k: "banner",       label: "Banner" },
  { k: "hero",         label: "Hero photo" },
];

export default function AdminAITools() {
  const router = useRouter();
  const [tab, setTab] = useState<"text" | "image">("text");
const swipe = useTabSwipe(["text", "image"] as const, tab, setTab);

  // Text gen state
  const [kind, setKind] = useState<Kind>("service_description");
  const [prompt, setPrompt] = useState("");
  const [existing, setExisting] = useState("");
  const [tone, setTone] = useState("professional");
  const [output, setOutput] = useState("");
  const [busy, setBusy] = useState(false);

  // Image gen state
  const [imgPrompt, setImgPrompt] = useState("");
  const [imgStyle, setImgStyle] = useState<ImgStyle>("flat-icon");
  const [imgB64, setImgB64] = useState<string | null>(null);
  const [imgBusy, setImgBusy] = useState(false);

  const genText = async () => {
    if (!prompt.trim()) return Alert.alert("Prompt required");
    setBusy(true); setOutput("");
    try {
      const { data } = await api.post<{ ok: boolean; text: string }>("/admin/ai/text", {
        kind, prompt: prompt.trim(), existing: existing.trim() || undefined, tone,
      });
      setOutput(data.text || "");
    } catch (e) {
      Alert.alert("AI error", formatApiError(e));
    } finally {
      setBusy(false);
    }
  };

  const genImage = async () => {
    if (!imgPrompt.trim()) return Alert.alert("Prompt required");
    setImgBusy(true); setImgB64(null);
    try {
      const { data } = await api.post<{ ok: boolean; image_b64: string; mime_type: string }>("/admin/ai/image", {
        prompt: imgPrompt.trim(), style: imgStyle,
      });
      if (data.image_b64) setImgB64(`data:${data.mime_type || "image/png"};base64,${data.image_b64}`);
    } catch (e) {
      Alert.alert("AI error", formatApiError(e));
    } finally {
      setImgBusy(false);
    }
  };

  const copyOutput = async () => {
    if (!output) return;
    await Clipboard.setStringAsync(output);
    Alert.alert("Copied", "Paste it into the category / service description field.");
  };

  const copyImageB64 = async () => {
    if (!imgB64) return;
    const raw = imgB64.replace(/^data:.*?;base64,/, "");
    await Clipboard.setStringAsync(raw);
    Alert.alert("Copied", "Base64 image string copied. Paste into the image_b64 field of the category / subcategory.");
  };

  return (
    <SafeAreaView style={s.safe} edges={["top"]} {...swipe}>
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={s.header}>
          <TouchableOpacity onPress={() => router.back()} style={s.iconBtn}>
            <Feather name="arrow-left" size={20} color={colors.textMain} />
          </TouchableOpacity>
          <Text style={s.title}>AI Tools</Text>
          <View style={{ width: 40 }} />
        </View>

        <View style={s.tabBar}>
          {(["text", "image"] as const).map((t) => (
            <TouchableOpacity
              key={t} onPress={() => setTab(t)}
              style={[s.tab, tab === t && s.tabActive]}
              testID={`ai-tab-${t}`}
            >
              <Feather name={t === "text" ? "type" : "image"} size={14} color={tab === t ? "#fff" : colors.textMain} />
              <Text style={[s.tabText, tab === t && { color: "#fff" }]}>{" "}{t === "text" ? "Generate text" : "Generate image"}</Text>
            </TouchableOpacity>
          ))}
        </View>

        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }} keyboardShouldPersistTaps="handled">
          {tab === "text" ? (
            <>
              <Text style={s.label}>WHAT TO GENERATE</Text>
              <View style={s.chipsRow}>
                {KINDS.map((kk) => (
                  <TouchableOpacity
                    key={kk.k}
                    onPress={() => setKind(kk.k)}
                    style={[s.chip, kind === kk.k && s.chipOn]}
                  >
                    <Text style={[s.chipText, kind === kk.k && { color: "#fff" }]}>{kk.label}</Text>
                  </TouchableOpacity>
                ))}
              </View>
              <Text style={s.label}>PROMPT</Text>
              <TextInput
                style={[s.input, { minHeight: 80, textAlignVertical: "top" }]}
                value={prompt} onChangeText={setPrompt}
                placeholder={KINDS.find((x) => x.k === kind)?.hint}
                placeholderTextColor={colors.textMuted}
                multiline
                testID="ai-prompt"
              />
              {kind === "improve" ? (
                <>
                  <Text style={s.label}>EXISTING TEXT</Text>
                  <TextInput
                    style={[s.input, { minHeight: 80, textAlignVertical: "top" }]}
                    value={existing} onChangeText={setExisting}
                    placeholder="Paste the original text to refine…"
                    placeholderTextColor={colors.textMuted}
                    multiline
                  />
                </>
              ) : null}
              <Text style={s.label}>TONE</Text>
              <View style={s.chipsRow}>
                {["professional", "friendly", "bold", "concise"].map((tn) => (
                  <TouchableOpacity key={tn} onPress={() => setTone(tn)} style={[s.chipSm, tone === tn && s.chipOn]}>
                    <Text style={[s.chipText, tone === tn && { color: "#fff" }]}>{tn}</Text>
                  </TouchableOpacity>
                ))}
              </View>
              <TouchableOpacity onPress={genText} disabled={busy} style={[s.primaryBtn, busy && { opacity: 0.6 }]} testID="ai-text-generate">
                {busy ? <ActivityIndicator color="#fff" /> : <Feather name="zap" size={16} color="#fff" />}
                <Text style={s.primaryBtnText}>{busy ? "  Thinking…" : "  Generate with AI"}</Text>
              </TouchableOpacity>
              {output ? (
                <View style={s.outputCard}>
                  <Text style={s.outputLabel}>OUTPUT</Text>
                  <Text style={s.outputText} selectable>{output}</Text>
                  <TouchableOpacity onPress={copyOutput} style={s.copyBtn}>
                    <Feather name="copy" size={14} color={colors.primary} />
                    <Text style={s.copyBtnText}>{"  "}Copy</Text>
                  </TouchableOpacity>
                </View>
              ) : null}
            </>
          ) : (
            <>
              <Text style={s.label}>PROMPT</Text>
              <TextInput
                style={[s.input, { minHeight: 80, textAlignVertical: "top" }]}
                value={imgPrompt} onChangeText={setImgPrompt}
                placeholder="e.g. “plumber holding a wrench, friendly cartoon”"
                placeholderTextColor={colors.textMuted}
                multiline
                testID="ai-img-prompt"
              />
              <Text style={s.label}>STYLE</Text>
              <View style={s.chipsRow}>
                {IMG_STYLES.map((st) => (
                  <TouchableOpacity key={st.k} onPress={() => setImgStyle(st.k)} style={[s.chip, imgStyle === st.k && s.chipOn]}>
                    <Text style={[s.chipText, imgStyle === st.k && { color: "#fff" }]}>{st.label}</Text>
                  </TouchableOpacity>
                ))}
              </View>
              <TouchableOpacity onPress={genImage} disabled={imgBusy} style={[s.primaryBtn, imgBusy && { opacity: 0.6 }]} testID="ai-img-generate">
                {imgBusy ? <ActivityIndicator color="#fff" /> : <Feather name="image" size={16} color="#fff" />}
                <Text style={s.primaryBtnText}>{imgBusy ? "  Painting…" : "  Generate image"}</Text>
              </TouchableOpacity>
              {imgB64 ? (
                <View style={s.outputCard}>
                  <Text style={s.outputLabel}>GENERATED IMAGE</Text>
                  <Image source={{ uri: imgB64 }} style={s.imgPreview} resizeMode="contain" />
                  <TouchableOpacity onPress={copyImageB64} style={s.copyBtn}>
                    <Feather name="copy" size={14} color={colors.primary} />
                    <Text style={s.copyBtnText}>{"  "}Copy base64… then paste in image field</Text>
                  </TouchableOpacity>
                </View>
              ) : null}
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 12, paddingVertical: 8,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  tabBar: { flexDirection: "row", padding: 8, gap: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  tab: {
    flex: 1, flexDirection: "row", justifyContent: "center", alignItems: "center",
    paddingVertical: 9, borderRadius: 999, backgroundColor: colors.surfaceMuted,
  },
  tabActive: { backgroundColor: colors.primary },
  tabText: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  label: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800", marginTop: 18, marginBottom: 8 },
  input: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radii.input, paddingHorizontal: 14, paddingVertical: 12,
    fontSize: 14, color: colors.textMain,
  },
  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    paddingHorizontal: 14, paddingVertical: 9,
    borderRadius: 999,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipSm: {
    paddingHorizontal: 12, paddingVertical: 7,
    borderRadius: 999, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 12, fontWeight: "700", color: colors.textMain },
  primaryBtn: {
    flexDirection: "row", justifyContent: "center", alignItems: "center",
    backgroundColor: colors.primary, paddingVertical: 14,
    borderRadius: radii.button, marginTop: 22,
  },
  primaryBtnText: { color: "#fff", fontWeight: "800", fontSize: 14 },
  outputCard: {
    marginTop: 18, padding: 14, backgroundColor: colors.surface,
    borderRadius: radii.card, borderWidth: 1, borderColor: colors.border,
  },
  outputLabel: { fontSize: 10, letterSpacing: 1.5, color: colors.textMuted, fontWeight: "800", marginBottom: 8 },
  outputText: { fontSize: 14, color: colors.textMain, lineHeight: 21 },
  copyBtn: { flexDirection: "row", alignItems: "center", marginTop: 12 },
  copyBtnText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  imgPreview: { width: "100%", height: 220, borderRadius: 12, backgroundColor: colors.surfaceMuted },
});
