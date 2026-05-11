// HelpGuide — reusable bottom-sheet walkthrough that mounts on admin screens.
// Auto-opens the first time a user visits the screen (tracked via AsyncStorage)
// and is reachable any time via a "?" help button in the header.
//
// Usage:
//   <HelpGuide id="products" title="How to create a product" steps={[...]} />
//   + a HelpButton({ onPress }) in your screen header.
import { useEffect, useState, useCallback } from "react";
import {
  View, Text, StyleSheet, Modal, ScrollView, TouchableOpacity, Pressable,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { colors, radii, spacing } from "./theme";

export type GuideStep = {
  icon: any;             // Feather icon name
  title: string;         // Bold step heading
  body: string;          // Plain helper text
  tip?: string;          // Optional small pro-tip line
  highlight?: string;    // Optional UI hint (e.g. "Tap the ➕ button at top-right")
};

type GuideProps = {
  id: string;                 // unique key for first-visit storage
  visible: boolean;
  title: string;
  subtitle?: string;
  steps: GuideStep[];
  onClose: () => void;
};

const STORAGE_PREFIX = "@help-guide-seen:";

// Public helper: check whether a guide has been shown before
export async function hasSeenGuide(id: string): Promise<boolean> {
  try {
    const v = await AsyncStorage.getItem(STORAGE_PREFIX + id);
    return !!v;
  } catch { return false; }
}

export async function markGuideSeen(id: string): Promise<void> {
  try { await AsyncStorage.setItem(STORAGE_PREFIX + id, "1"); } catch { /* ignore */ }
}

// Hook: returns initialVisible (true on first visit), and a setter.
export function useFirstVisitGuide(id: string) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const seen = await hasSeenGuide(id);
      if (!seen && !cancelled) setVisible(true);
    })();
    return () => { cancelled = true; };
  }, [id]);
  const close = useCallback(() => {
    setVisible(false);
    markGuideSeen(id);
  }, [id]);
  const open = useCallback(() => setVisible(true), []);
  return { visible, open, close };
}

export function HelpGuide({ id, visible, title, subtitle, steps, onClose }: GuideProps) {
  const [idx, setIdx] = useState(0);
  useEffect(() => { if (visible) setIdx(0); }, [visible]);

  const isLast = idx === steps.length - 1;
  const step = steps[idx];
  if (!step) return null;

  const handleClose = () => {
    markGuideSeen(id);
    onClose();
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={handleClose}>
      <Pressable style={styles.overlay} onPress={handleClose}>
        <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
          {/* Drag handle */}
          <View style={styles.handle} />

          {/* Header */}
          <View style={styles.header}>
            <View style={{ flex: 1 }}>
              <Text style={styles.eyebrow}>STEP {idx + 1} OF {steps.length}</Text>
              <Text style={styles.title}>{title}</Text>
              {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
            </View>
            <TouchableOpacity onPress={handleClose} style={styles.closeBtn} testID="help-close">
              <Feather name="x" size={20} color={colors.textMain} />
            </TouchableOpacity>
          </View>

          {/* Progress dots */}
          <View style={styles.dotsRow}>
            {steps.map((_, i) => (
              <View key={i} style={[styles.dot, i === idx && styles.dotActive, i < idx && styles.dotDone]} />
            ))}
          </View>

          {/* Step content */}
          <ScrollView contentContainerStyle={styles.body} showsVerticalScrollIndicator={false}>
            <View style={styles.iconCircle}>
              <Feather name={step.icon} size={28} color={colors.primary} />
            </View>
            <Text style={styles.stepTitle}>{step.title}</Text>
            <Text style={styles.stepBody}>{step.body}</Text>

            {step.highlight ? (
              <View style={styles.highlightCard}>
                <Feather name="zap" size={14} color={colors.primary} />
                <Text style={styles.highlightText}>{step.highlight}</Text>
              </View>
            ) : null}

            {step.tip ? (
              <View style={styles.tipCard}>
                <Feather name="info" size={13} color="#92400E" />
                <Text style={styles.tipText}>{step.tip}</Text>
              </View>
            ) : null}
          </ScrollView>

          {/* Footer / nav */}
          <View style={styles.footer}>
            <TouchableOpacity
              onPress={() => setIdx((i) => Math.max(0, i - 1))}
              disabled={idx === 0}
              style={[styles.navBtn, idx === 0 && { opacity: 0.3 }]}
              testID="help-prev"
            >
              <Feather name="chevron-left" size={18} color={colors.textMain} />
              <Text style={styles.navBtnText}>Back</Text>
            </TouchableOpacity>

            {isLast ? (
              <TouchableOpacity onPress={handleClose} style={styles.primaryBtn} testID="help-done">
                <Feather name="check" size={16} color={colors.primaryFg} />
                <Text style={styles.primaryBtnText}>Got it!</Text>
              </TouchableOpacity>
            ) : (
              <TouchableOpacity onPress={() => setIdx((i) => Math.min(steps.length - 1, i + 1))} style={styles.primaryBtn} testID="help-next">
                <Text style={styles.primaryBtnText}>Next</Text>
                <Feather name="chevron-right" size={16} color={colors.primaryFg} />
              </TouchableOpacity>
            )}
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

// Convenience button to mount in screen headers
export function HelpButton({ onPress, testID }: { onPress: () => void; testID?: string }) {
  return (
    <TouchableOpacity onPress={onPress} style={styles.helpBtn} testID={testID || "help-open"}>
      <Feather name="help-circle" size={18} color={colors.primary} />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.background, borderTopLeftRadius: 28, borderTopRightRadius: 28, paddingBottom: 16, maxHeight: "85%" },
  handle: { width: 38, height: 4, borderRadius: 999, backgroundColor: colors.border, alignSelf: "center", marginTop: 8, marginBottom: 4 },
  header: { flexDirection: "row", alignItems: "flex-start", paddingHorizontal: 20, paddingTop: 8, paddingBottom: 6 },
  eyebrow: { fontSize: 10, fontWeight: "900", letterSpacing: 1.6, color: colors.primary, marginBottom: 2 },
  title: { fontSize: 19, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  subtitle: { fontSize: 12, color: colors.textMuted, marginTop: 4, lineHeight: 18 },
  closeBtn: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  dotsRow: { flexDirection: "row", paddingHorizontal: 20, paddingTop: 8, paddingBottom: 4, gap: 4 },
  dot: { flex: 1, height: 4, borderRadius: 2, backgroundColor: colors.border },
  dotActive: { backgroundColor: colors.primary },
  dotDone: { backgroundColor: colors.primary, opacity: 0.4 },
  body: { paddingHorizontal: 24, paddingTop: 14, paddingBottom: 14 },
  iconCircle: { width: 64, height: 64, borderRadius: 32, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center", marginBottom: 14 },
  stepTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3, marginBottom: 6 },
  stepBody: { fontSize: 14, color: colors.textMain, lineHeight: 22 },
  highlightCard: { flexDirection: "row", alignItems: "flex-start", gap: 8, marginTop: 12, padding: 12, borderRadius: 12, backgroundColor: colors.brand100, borderWidth: 1, borderColor: colors.primary + "33" },
  highlightText: { fontSize: 12, fontWeight: "700", color: colors.primary, flex: 1, lineHeight: 18 },
  tipCard: { flexDirection: "row", alignItems: "flex-start", gap: 8, marginTop: 10, padding: 10, borderRadius: 10, backgroundColor: "#FEF3C7" },
  tipText: { fontSize: 11, color: "#92400E", flex: 1, lineHeight: 16 },
  footer: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 20, paddingTop: 10, gap: 10, borderTopWidth: 1, borderTopColor: colors.border },
  navBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 14, paddingVertical: 10, borderRadius: 999 },
  navBtnText: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  primaryBtn: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: 18, paddingVertical: 10, borderRadius: 999, backgroundColor: colors.primary },
  primaryBtnText: { fontSize: 13, fontWeight: "800", color: colors.primaryFg },
  helpBtn: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center", backgroundColor: colors.brand100, borderWidth: 1, borderColor: colors.primary + "33" },
});
