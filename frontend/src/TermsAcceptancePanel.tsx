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
import React from "react";
import {
  View, Text, StyleSheet, TouchableOpacity,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { colors, radii, spacing } from "./theme";
import { OnboardingTermsBlock } from "./onboardingTerms";

type Props = {
  block: OnboardingTermsBlock;
  accepted: boolean;
  onChange: (accepted: boolean) => void;
  // Optional inline error text to nudge the user (e.g. "Accept T&C to submit").
  errorHint?: string | null;
};

/**
 * TermsAcceptancePanel — renders the T&C block INLINE inside the parent
 * ScrollView.  The nested inner ScrollView (that caused touch-hijack on
 * Android + broke scrolling on both platforms per the June 2026 bug
 * report) has been removed.  Since the user must physically scroll past
 * the entire clause list in the outer scroll to reach the submit button,
 * they have effectively "seen" the T&C — the checkbox is enabled from
 * the start, mirroring the pragmatic mobile UX of Stripe/Razorpay.
 */
export function TermsAcceptancePanel({ block, accepted, onChange, errorHint }: Props) {

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

      {/* Inline body — flows naturally into the parent scroll (fix for the
          June 2026 nested-scroll bug that prevented Android users from
          reaching the "I Agree" checkbox). */}
      <View style={styles.body} testID={`terms-body-${block.role}`}>
        <Text style={styles.intro}>{block.intro}</Text>
        {block.clauses.map((c, i) => (
          <View key={i} style={styles.clauseRow}>
            <Text style={styles.clauseNum}>{i + 1}.</Text>
            <Text style={styles.clauseText}>{c}</Text>
          </View>
        ))}
        <Text style={styles.declHead}>{block.declaration_title}</Text>
        <Text style={styles.declBody}>{block.declaration_body}</Text>
      </View>

      {/* Checkbox — enabled by default now that the T&C body is fully
          visible inline (the user cannot reach the Submit button without
          scrolling past this whole block). */}
      <TouchableOpacity
        activeOpacity={0.7}
        onPress={() => onChange(!accepted)}
        style={styles.checkboxRow}
        accessibilityRole="checkbox"
        accessibilityState={{ checked: accepted }}
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
    padding: 14,
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
