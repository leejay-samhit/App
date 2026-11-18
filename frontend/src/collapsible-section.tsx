/**
 * Collapsible section (Nov-2026, req 19).
 *
 * Used on long admin screens — the System Wallet in particular — so a page
 * full of ledgers can be scanned by heading first and opened on demand. Purely
 * presentational: the content and every figure inside stay exactly as they are.
 */
import { ReactNode, useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, LayoutAnimation, Platform, UIManager } from "react-native";
import { Feather } from "@expo/vector-icons";
import { colors, radii } from "./theme";

if (Platform.OS === "android" && UIManager.setLayoutAnimationEnabledExperimental) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

type Props = {
  title: string;
  /** Right-hand summary, e.g. a total — visible while collapsed. */
  summary?: string;
  icon?: keyof typeof Feather.glyphMap;
  defaultOpen?: boolean;
  children: ReactNode;
  testID?: string;
};

export function CollapsibleSection({
  title,
  summary,
  icon = "folder",
  defaultOpen = false,
  children,
  testID,
}: Props) {
  const [open, setOpen] = useState(defaultOpen);

  const toggle = () => {
    LayoutAnimation.configureNext(LayoutAnimation.Presets.easeInEaseOut);
    setOpen((v) => !v);
  };

  return (
    <View style={styles.wrap}>
      <TouchableOpacity onPress={toggle} style={styles.header} activeOpacity={0.75} testID={testID}>
        <View style={styles.iconWrap}>
          <Feather name={icon} size={15} color={colors.primary} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>{title}</Text>
          {summary ? <Text style={styles.summary} numberOfLines={1}>{summary}</Text> : null}
        </View>
        <Feather name={open ? "chevron-up" : "chevron-down"} size={18} color={colors.textMuted} />
      </TouchableOpacity>
      {open ? <View style={styles.body}>{children}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: colors.surface,
    borderRadius: radii.card,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    marginBottom: 10,
    overflow: "hidden",
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 14,
    paddingVertical: 14,
    minHeight: 56,
  },
  iconWrap: {
    width: 30,
    height: 30,
    borderRadius: 10,
    backgroundColor: colors.surfaceMuted,
    alignItems: "center",
    justifyContent: "center",
  },
  title: { fontSize: 13.5, fontWeight: "800", color: colors.textMain, letterSpacing: 0.2 },
  summary: { fontSize: 11.5, color: colors.textMuted, marginTop: 2, fontVariant: ["tabular-nums"] },
  body: { paddingHorizontal: 12, paddingBottom: 14 },
});
