// Shared date-range filter (Oct 2026).
//
// ONE date picker for the whole app: quick presets + a real calendar for
// "Choose date". Every screen that used to show a raw "YYYY-MM-DD" text box
// now renders this, so a date filter behaves identically everywhere and can
// never be typed wrong.
import React, { useMemo, useState } from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, Modal, ScrollView, Platform,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import { Calendar } from "react-native-calendars";
import { colors, spacing, radii } from "./theme";

export type DateRange = { from: string; to: string };   // "" = unbounded

const pad = (n: number) => String(n).padStart(2, "0");
export const toISODate = (d: Date) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

const shiftDays = (n: number) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return toISODate(d);
};

const PRESETS: { key: string; label: string; range: () => DateRange }[] = [
  { key: "all", label: "All time", range: () => ({ from: "", to: "" }) },
  { key: "today", label: "Today", range: () => ({ from: toISODate(new Date()), to: toISODate(new Date()) }) },
  { key: "7d", label: "Last 7 days", range: () => ({ from: shiftDays(6), to: toISODate(new Date()) }) },
  { key: "30d", label: "Last 30 days", range: () => ({ from: shiftDays(29), to: toISODate(new Date()) }) },
  {
    key: "month", label: "This month",
    range: () => {
      const d = new Date();
      return { from: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-01`, to: toISODate(d) };
    },
  },
];

const pretty = (iso: string) => {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(d)} ${months[Number(m) - 1] || ""} ${y}`;
};

export function rangeLabel(r: DateRange): string {
  if (!r.from && !r.to) return "All time";
  if (r.from && r.to) return r.from === r.to ? pretty(r.from) : `${pretty(r.from)} → ${pretty(r.to)}`;
  return r.from ? `From ${pretty(r.from)}` : `Until ${pretty(r.to)}`;
}

/**
 * Tap-to-open date range filter. Renders as a single compact button plus the
 * preset chips; "Choose dates" opens the calendar where the first tap sets
 * the start and the second the end.
 */
export function DateRangeFilter({
  value,
  onChange,
  compact = false,
  testID = "date-range",
}: {
  value: DateRange;
  onChange: (r: DateRange) => void;
  compact?: boolean;
  testID?: string;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<DateRange>(value);

  const activePreset = useMemo(() => {
    for (const p of PRESETS) {
      const r = p.range();
      if (r.from === value.from && r.to === value.to) return p.key;
    }
    return "custom";
  }, [value]);

  const marked = useMemo(() => {
    const out: Record<string, any> = {};
    if (!draft.from) return out;
    out[draft.from] = {
      startingDay: true, color: colors.primary, textColor: colors.primaryFg,
    };
    if (draft.to && draft.to !== draft.from) {
      const cur = new Date(draft.from);
      const end = new Date(draft.to);
      cur.setDate(cur.getDate() + 1);
      while (cur < end) {
        out[toISODate(cur)] = { color: colors.brand100, textColor: colors.textMain };
        cur.setDate(cur.getDate() + 1);
      }
      out[draft.to] = { endingDay: true, color: colors.primary, textColor: colors.primaryFg };
    } else {
      out[draft.from].endingDay = true;
    }
    return out;
  }, [draft]);

  const onDayPress = (day: { dateString: string }) => {
    const d = day.dateString;
    if (!draft.from || (draft.from && draft.to)) {
      setDraft({ from: d, to: "" });
    } else if (d < draft.from) {
      setDraft({ from: d, to: draft.from });
    } else {
      setDraft({ from: draft.from, to: d });
    }
  };

  return (
    <View testID={testID}>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={s.chipRow}
      >
        {PRESETS.map((p) => {
          const on = activePreset === p.key;
          return (
            <TouchableOpacity
              key={p.key}
              style={[s.chip, on && s.chipOn]}
              onPress={() => onChange(p.range())}
              testID={`${testID}-preset-${p.key}`}
            >
              <Text style={[s.chipText, on && s.chipTextOn]}>{p.label}</Text>
            </TouchableOpacity>
          );
        })}
        <TouchableOpacity
          style={[s.chip, activePreset === "custom" && s.chipOn]}
          onPress={() => { setDraft(value); setOpen(true); }}
          testID={`${testID}-open`}
        >
          <Feather
            name="calendar"
            size={13}
            color={activePreset === "custom" ? colors.primaryFg : colors.textMain}
          />
          <Text style={[s.chipText, activePreset === "custom" && s.chipTextOn]}>
            {activePreset === "custom" ? rangeLabel(value) : "Choose dates"}
          </Text>
        </TouchableOpacity>
      </ScrollView>

      {!compact ? (
        <Text style={s.summary} testID={`${testID}-label`}>{rangeLabel(value)}</Text>
      ) : null}

      <Modal visible={open} transparent animationType="slide" onRequestClose={() => setOpen(false)}>
        <View style={s.overlay}>
          <View style={s.sheet}>
            <View style={s.handle} />
            <Text style={s.title}>Choose dates</Text>
            <Text style={s.sub}>
              {draft.from && !draft.to
                ? `Start ${pretty(draft.from)} — now tap the end date`
                : rangeLabel(draft)}
            </Text>
            <Calendar
              markingType="period"
              markedDates={marked}
              onDayPress={onDayPress}
              maxDate={toISODate(new Date())}
              enableSwipeMonths
              theme={{
                calendarBackground: colors.surface,
                monthTextColor: colors.textMain,
                textMonthFontWeight: "800",
                dayTextColor: colors.textMain,
                textDisabledColor: colors.border,
                arrowColor: colors.primary,
                todayTextColor: colors.accent,
                textDayFontWeight: "600",
                textDayHeaderFontWeight: "700",
              }}
              testID={`${testID}-calendar`}
            />
            <View style={s.btnRow}>
              <TouchableOpacity
                style={[s.btn, { backgroundColor: colors.surfaceMuted }]}
                onPress={() => { setDraft({ from: "", to: "" }); onChange({ from: "", to: "" }); setOpen(false); }}
                testID={`${testID}-clear`}
              >
                <Text style={{ color: colors.textMain, fontWeight: "700" }}>Clear</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[s.btn, { backgroundColor: colors.primary }]}
                onPress={() => {
                  onChange({ from: draft.from, to: draft.to || draft.from });
                  setOpen(false);
                }}
                testID={`${testID}-apply`}
              >
                <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>Apply</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const s = StyleSheet.create({
  chipRow: { gap: 8, paddingHorizontal: spacing.screen, paddingVertical: 4 },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 13, paddingVertical: 9, borderRadius: 999,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    minHeight: 36, justifyContent: "center",
  },
  chipOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 12.5, fontWeight: "700", color: colors.textMain },
  chipTextOn: { color: colors.primaryFg },
  summary: {
    fontSize: 11.5, fontWeight: "700", color: colors.textMuted,
    paddingHorizontal: spacing.screen, marginTop: 6,
  },
  overlay: { flex: 1, backgroundColor: "#00000066", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.surface, borderTopLeftRadius: 22, borderTopRightRadius: 22,
    padding: spacing.screen, paddingBottom: Platform.OS === "ios" ? 34 : spacing.screen,
  },
  handle: {
    width: 42, height: 4, borderRadius: 2, backgroundColor: colors.border,
    alignSelf: "center", marginBottom: 12,
  },
  title: { fontSize: 17, fontWeight: "900", color: colors.textMain },
  sub: { fontSize: 12, color: colors.textMuted, fontWeight: "600", marginTop: 4, marginBottom: 10 },
  btnRow: { flexDirection: "row", gap: 10, marginTop: 14 },
  btn: {
    flex: 1, borderRadius: radii.button, paddingVertical: 13,
    alignItems: "center", justifyContent: "center", minHeight: 48,
  },
});
