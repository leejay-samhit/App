/**
 * TermsAcceptancePanel — mobile mirror of the web
 * `frontend/src/components/TermsAcceptancePanel.jsx`.
 *
 * Gate behaviour (mirrors web 1:1):
 *   • Renders the T&C block inside a bordered scrollable card (~340px tall).
 *   • Watches native `onScroll` on the inner ScrollView; once the user
 *     scrolls to within 8px of the bottom (OR the content fits entirely
 *     within the visible height), the "I Agree" checkbox unlocks.
 *   • The parent screen consumes `accepted` via the `onChange` callback and
 *     wires it to the submit-button disabled state.
 *
 * Also renders a "Scroll to bottom to enable the I Agree checkbox" hint at
 * the bottom of the panel until the gate is cleared, mirroring the web UX.
 */
import React, { useRef, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  NativeScrollEvent, NativeSyntheticEvent, LayoutChangeEvent,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { colors, radii, spacing } from "./theme";
import { OnboardingTermsBlock } from "./onboardingTerms";

// Scroll-bottom detection tolerance in pixels. Mirrors the web threshold.
const SCROLL_BOTTOM_TOLERANCE = 8;

type Props = {
  block: OnboardingTermsBlock;
  accepted: boolean;
  onChange: (accepted: boolean) => void;
  // Optional inline error text to nudge the user (e.g. "Accept T&C to submit").
  errorHint?: string | null;
};

export function TermsAcceptancePanel({ block, accepted, onChange, errorHint }: Props) {
  const [canAccept, setCanAccept] = useState(false);
  // Layout metrics — used to detect the case where content already fits
  // inside the panel (no scrolling required) so the gate unlocks up-front.
  const contentHeightRef = useRef(0);
  const visibleHeightRef = useRef(0);

  const evaluateScrollGate = () => {
    const c = contentHeightRef.current;
    const v = visibleHeightRef.current;
    if (c > 0 && v > 0 && c <= v) {
      // Panel content already fits — no scroll needed.
      setCanAccept(true);
    }
  };

  const onContentSizeChange = (_w: number, h: number) => {
    contentHeightRef.current = h;
    evaluateScrollGate();
  };
  const onScrollViewLayout = (e: LayoutChangeEvent) => {
    visibleHeightRef.current = e.nativeEvent.layout.height;
    evaluateScrollGate();
  };
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
    const distanceFromBottom =
      contentSize.height - (contentOffset.y + layoutMeasurement.height);
    if (distanceFromBottom <= SCROLL_BOTTOM_TOLERANCE) {
      setCanAccept(true);
    }
  };

  return (
    <View style={styles.card}>
      {/* Header */}
      <View style={styles.header}>
        <View style={styles.iconWrap}>
          <Feather name="file-text" size={16} color={colors.primary} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.title} numberOfLines={2}>{block.title}</Text>
          <Text style={styles.hint}>Please read carefully — you must accept before continuing.</Text>
        </View>
        <View style={styles.versionPill} accessibilityLabel={`Version ${block.version}`}>
          <Text style={styles.versionPillText}>v{block.version}</Text>
        </View>
      </View>

      {/* Scrollable body */}
      <ScrollView
        style={styles.body}
        contentContainerStyle={{ padding: 14, paddingBottom: 18 }}
        onScroll={onScroll}
        scrollEventThrottle={64}
        onContentSizeChange={onContentSizeChange}
        onLayout={onScrollViewLayout}
        showsVerticalScrollIndicator
        testID={`terms-body-${block.role}`}
      >
        <Text style={styles.intro}>{block.intro}</Text>
        {block.clauses.map((c, i) => (
          <View key={i} style={styles.clauseRow}>
            <Text style={styles.clauseNum}>{i + 1}.</Text>
            <Text style={styles.clauseText}>{c}</Text>
          </View>
        ))}
        <Text style={styles.declHead}>{block.declaration_title}</Text>
        <Text style={styles.declBody}>{block.declaration_body}</Text>
      </ScrollView>

      {/* Gate hint */}
      {!canAccept ? (
        <View style={styles.gateHint}>
          <Feather name="chevron-down" size={12} color={colors.primary} />
          <Text style={styles.gateHintText}>Scroll to bottom to enable the “I Agree” checkbox</Text>
        </View>
      ) : null}

      {/* Checkbox */}
      <TouchableOpacity
        activeOpacity={0.7}
        disabled={!canAccept}
        onPress={() => onChange(!accepted)}
        style={[styles.checkboxRow, !canAccept && { opacity: 0.5 }]}
        accessibilityRole="checkbox"
        accessibilityState={{ checked: accepted, disabled: !canAccept }}
        testID={`terms-agree-${block.role}`}
      >
        <View style={[styles.checkbox, accepted && styles.checkboxOn]}>
          {accepted ? <Feather name="check" size={13} color="#fff" /> : null}
        </View>
        <Text style={styles.checkboxLabel}>{block.agree_label}</Text>
      </TouchableOpacity>

      {errorHint ? (
        <View style={styles.errorHint}>
          <Feather name="alert-circle" size={13} color="#B91C1C" />
          <Text style={styles.errorHintText}>{errorHint}</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
    marginTop: spacing.md,
  },
  header: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
    padding: 12,
    backgroundColor: colors.primary + "0D",
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  iconWrap: {
    width: 32, height: 32, borderRadius: 8,
    backgroundColor: colors.primary + "1A",
    alignItems: "center", justifyContent: "center",
  },
  title: {
    fontSize: 14, fontWeight: "800",
    color: colors.textMain, letterSpacing: -0.2,
  },
  hint: {
    fontSize: 11, color: colors.textMuted, marginTop: 2, letterSpacing: 0.1,
  },
  versionPill: {
    backgroundColor: colors.primary,
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 999,
  },
  versionPillText: {
    fontSize: 10, color: colors.primaryFg, fontWeight: "800", letterSpacing: 0.4,
  },
  body: {
    maxHeight: 340,
    backgroundColor: "#FBFCFB",
  },
  intro: {
    fontSize: 12, color: colors.textMain, marginBottom: 8, lineHeight: 18,
  },
  clauseRow: {
    flexDirection: "row",
    gap: 6,
    marginBottom: 8,
    paddingRight: 4,
  },
  clauseNum: {
    fontSize: 12, fontWeight: "800", color: colors.primary, width: 20,
  },
  clauseText: {
    flex: 1, fontSize: 12, color: colors.textMain, lineHeight: 18, letterSpacing: 0.1,
  },
  declHead: {
    marginTop: 8, marginBottom: 4,
    fontSize: 12, fontWeight: "900", color: colors.textMain, letterSpacing: 0.2,
  },
  declBody: {
    fontSize: 11.5, color: colors.textMuted, lineHeight: 17,
  },
  gateHint: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 12,
    paddingTop: 8,
  },
  gateHintText: {
    fontSize: 11, color: colors.primary, fontWeight: "700",
  },
  checkboxRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
    padding: 12,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    backgroundColor: colors.surface,
    marginTop: 4,
  },
  checkbox: {
    width: 22, height: 22, borderRadius: 6,
    borderWidth: 2, borderColor: colors.primary,
    alignItems: "center", justifyContent: "center",
    marginTop: 1,
  },
  checkboxOn: {
    backgroundColor: colors.primary,
  },
  checkboxLabel: {
    flex: 1, fontSize: 12, color: colors.textMain,
    lineHeight: 17, fontWeight: "700",
  },
  errorHint: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    padding: 10,
    backgroundColor: "#FEE2E2",
    borderTopWidth: 1,
    borderTopColor: "#FCA5A5",
  },
  errorHintText: {
    flex: 1, fontSize: 11, color: "#B91C1C", fontWeight: "700",
  },
});
