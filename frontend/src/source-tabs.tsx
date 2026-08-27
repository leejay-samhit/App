// Reusable "join source" category tab bar used by Admin → Users and
// Admin → Registration fee revenue. Shows a pill per category with a live
// count (and optional amount) so admins can see the split at a glance.
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from "react-native";
import { Feather } from "@expo/vector-icons";
import { colors, formatINR } from "./theme";

export type SourceTab = {
  key: string;
  label: string;
  icon: keyof typeof Feather.glyphMap;
  count?: number;
  amount?: number;
};

export function SourceTabs({
  tabs,
  value,
  onChange,
  showAmount,
  testIDPrefix = "source-tab",
}: {
  tabs: SourceTab[];
  value: string;
  onChange: (key: string) => void;
  showAmount?: boolean;
  testIDPrefix?: string;
}) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.row}
    >
      {tabs.map((t) => {
        const active = value === t.key;
        return (
          <TouchableOpacity
            key={t.key}
            onPress={() => onChange(t.key)}
            style={[styles.chip, active && styles.chipActive]}
            testID={`${testIDPrefix}-${t.key}`}
            activeOpacity={0.8}
          >
            <Feather name={t.icon} size={13} color={active ? colors.primaryFg : colors.primary} />
            <Text style={[styles.label, active && styles.labelActive]} numberOfLines={1}>
              {t.label}
            </Text>
            {typeof t.count === "number" ? (
              <View style={[styles.badge, active && styles.badgeActive]}>
                <Text style={[styles.badgeText, active && styles.badgeTextActive]}>{t.count}</Text>
              </View>
            ) : null}
            {showAmount && typeof t.amount === "number" ? (
              <Text style={[styles.amount, active && styles.labelActive]}>{formatINR(t.amount)}</Text>
            ) : null}
          </TouchableOpacity>
        );
      })}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: { gap: 8, paddingVertical: 4, paddingRight: 8 },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    minHeight: 44,
    borderRadius: 999,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  label: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  labelActive: { color: colors.primaryFg },
  badge: {
    minWidth: 22,
    paddingHorizontal: 5,
    paddingVertical: 1,
    borderRadius: 999,
    backgroundColor: colors.brand100,
    alignItems: "center",
  },
  badgeActive: { backgroundColor: "rgba(255,255,255,0.25)" },
  badgeText: { fontSize: 11, fontWeight: "900", color: colors.primary },
  badgeTextActive: { color: colors.primaryFg },
  amount: { fontSize: 11, fontWeight: "700", color: colors.textMuted, marginLeft: 2 },
});
