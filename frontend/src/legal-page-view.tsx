// Shared component that fetches a legal page from /api/legal/{kind} and
// renders it. Lines starting with `## ` become headings, blank lines
// separate paragraphs. Falls back gracefully if the API errors.
import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "../src/api";
import { colors, spacing } from "../src/theme";

type Props = {
  kind: "privacy" | "terms" | "refund" | "contact_us";
  title: string;
};

export default function LegalPageView({ kind, title }: Props) {
  const router = useRouter();
  const [text, setText] = useState<string>("");
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const { data } = await api.get(`/legal/${kind}`);
        if (mounted) {
          setText(data?.content_text || "");
          setUpdatedAt(data?.updated_at || null);
        }
      } catch {
        if (mounted) setText("Failed to load. Please try again later.");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => { mounted = false; };
  }, [kind]);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn}><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>{title}</Text>
        <View style={{ width: 40 }} />
      </View>
      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 60 }}>
          {updatedAt ? (
            <Text style={styles.metaLine}>Last updated · {new Date(updatedAt).toLocaleDateString()}</Text>
          ) : null}
          {text.split(/\n\n+/).map((para, idx) => {
            const trimmed = para.trim();
            if (!trimmed) return null;
            if (trimmed.startsWith("## ")) {
              return <Text key={idx} style={styles.h2}>{trimmed.replace(/^##\s+/, "")}</Text>;
            }
            return <Text key={idx} style={styles.p}>{trimmed}</Text>;
          })}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 12, paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  backBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  title: { fontSize: 16, fontWeight: "800", color: colors.textMain },
  metaLine: { fontSize: 11, color: colors.textMuted, fontWeight: "700", marginBottom: 12 },
  h2: { fontSize: 16, fontWeight: "900", color: colors.textMain, marginTop: 18, marginBottom: 4 },
  p: { fontSize: 14, color: colors.textMain, lineHeight: 22, marginBottom: 10 },
});
