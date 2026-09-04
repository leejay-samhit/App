/**
 * VariantEditor — size / RAM-ROM options with their own stock & price.
 *
 * Jun 2026, owner spec: "when Fashion category is selected, between price
 * and stock let the vendor add S M L XL XXL with stock … use the universal
 * measurement per product type so customers aren't confused … same for
 * mobiles: RAM and ROM, and when RAM/ROM increases the price increases."
 *
 * How it works for the vendor:
 *   1. Pick a chart (Apparel · Footwear UK/EU · Kids · Waist inches ·
 *      Free size · Mobile RAM-ROM · Custom). Charts come from the SERVER
 *      (GET /api/product-variant-charts) so app and web never disagree.
 *   2. Tap the sizes they actually stock — each becomes a row.
 *   3. Type stock (and a price difference, or a full price) per row.
 *
 * The product's own Stock field is then computed server-side as the sum of
 * the options, and its price becomes the cheapest buyable option, so every
 * existing stock badge / price filter keeps working untouched.
 */
import React, { useEffect, useMemo, useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, ScrollView } from "react-native";
import { Feather } from "@expo/vector-icons";
import { colors } from "./theme";
import { api } from "./api";

export type VariantRow = {
  id?: string;
  label: string;
  stock: string;        // kept as strings while editing
  price_extra: string;
  price_abs: string;
  active?: boolean;
};

type Chart = {
  value: string;
  label: string;
  hint: string;
  unit: string;
  columns: string[];
  options: { label: string }[];
  guide: string[][];
};

export type VariantState = {
  chart: string;
  priceMode: "extra" | "absolute";
  rows: VariantRow[];
};

export const emptyVariantState: VariantState = { chart: "", priceMode: "extra", rows: [] };

/** Build the API payload fragment. Returns `{}` when the vendor added none. */
export function variantPayload(v: VariantState) {
  if (!v.chart || v.rows.length === 0) {
    return { variant_chart: "", variant_price_mode: "extra", variants: [] };
  }
  return {
    variant_chart: v.chart,
    variant_price_mode: v.priceMode,
    variants: v.rows.map((r) => ({
      id: r.id,
      label: r.label,
      stock: Number(r.stock) || 0,
      price_extra: Number(r.price_extra) || 0,
      price_abs: Number(r.price_abs) || 0,
      active: r.active !== false,
    })),
  };
}

/** Hydrate from an existing product document. */
export function variantStateFrom(existing: any): VariantState {
  const rows: VariantRow[] = Array.isArray(existing?.variants)
    ? existing.variants.map((v: any) => ({
        id: v.id,
        label: String(v.label || ""),
        stock: String(v.stock ?? 0),
        price_extra: String(v.price_extra ?? 0),
        price_abs: String(v.price_abs ?? 0),
        active: v.active !== false,
      }))
    : [];
  return {
    chart: String(existing?.variant_chart || ""),
    priceMode: existing?.variant_price_mode === "absolute" ? "absolute" : "extra",
    rows,
  };
}

export function VariantEditor({
  value, onChange, basePrice,
}: { value: VariantState; onChange: (v: VariantState) => void; basePrice: number }) {
  const [charts, setCharts] = useState<Chart[]>([]);
  const [customLabel, setCustomLabel] = useState("");

  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const r = await api.get<{ charts: Chart[] }>("/product-variant-charts");
        if (!dead) setCharts(r.data?.charts || []);
      } catch { /* offline — vendor can still use "Custom" once charts load */ }
    })();
    return () => { dead = true; };
  }, []);

  const chart = useMemo(() => charts.find((c) => c.value === value.chart) || null, [charts, value.chart]);
  const chosen = new Set(value.rows.map((r) => r.label.toLowerCase()));

  const setChart = (v: string) => {
    // Switching chart clears rows — mixing S/M/L with UK 7/8/9 is never right.
    onChange({ ...value, chart: v === value.chart ? "" : v, rows: v === value.chart ? [] : [] });
  };

  const toggleOption = (label: string) => {
    const key = label.toLowerCase();
    if (chosen.has(key)) {
      onChange({ ...value, rows: value.rows.filter((r) => r.label.toLowerCase() !== key) });
    } else {
      onChange({
        ...value,
        rows: [...value.rows, { label, stock: "0", price_extra: "0", price_abs: String(basePrice || 0), active: true }],
      });
    }
  };

  const patchRow = (i: number, patch: Partial<VariantRow>) => {
    const rows = [...value.rows];
    rows[i] = { ...rows[i], ...patch };
    onChange({ ...value, rows });
  };

  const totalStock = value.rows.reduce((a, r) => a + (Number(r.stock) || 0), 0);
  const num = (s: string) => (s === "" ? "" : s.replace(/[^0-9.]/g, ""));

  return (
    <View style={st.wrap}>
      <View style={st.headRow}>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={st.title}>Sizes / options</Text>
          <Text style={st.hint}>
            Optional. Add these and the Stock field above is calculated for you
            (total across all options).
          </Text>
        </View>
        {value.rows.length > 0 ? (
          <View style={st.totalPill}><Text style={st.totalPillText}>{totalStock} pcs</Text></View>
        ) : null}
      </View>

      {/* Chart picker */}
      <Text style={st.label}>Which size chart fits this product?</Text>
      <View style={st.chipWrap}>
        {charts.map((c) => (
          <TouchableOpacity
            key={c.value}
            onPress={() => setChart(c.value)}
            style={[st.chip, value.chart === c.value && st.chipOn]}
            testID={`variant-chart-${c.value}`}
          >
            <Text style={[st.chipText, value.chart === c.value && { color: colors.primaryFg }]}>{c.label}</Text>
          </TouchableOpacity>
        ))}
      </View>
      {chart ? <Text style={st.hint}>{chart.hint}</Text> : null}

      {chart ? (
        <>
          {/* Price mode */}
          <Text style={st.label}>How is the price set?</Text>
          <View style={st.chipWrap}>
            <TouchableOpacity
              onPress={() => onChange({ ...value, priceMode: "extra" })}
              style={[st.chip, value.priceMode === "extra" && st.chipOn]}
              testID="variant-mode-extra"
            >
              <Text style={[st.chipText, value.priceMode === "extra" && { color: colors.primaryFg }]}>Base + extra</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => onChange({ ...value, priceMode: "absolute" })}
              style={[st.chip, value.priceMode === "absolute" && st.chipOn]}
              testID="variant-mode-absolute"
            >
              <Text style={[st.chipText, value.priceMode === "absolute" && { color: colors.primaryFg }]}>Full price each</Text>
            </TouchableOpacity>
          </View>
          <Text style={st.hint}>
            {value.priceMode === "extra"
              ? `Base price ₹${basePrice || 0} applies to every option; type only the difference (e.g. XL = 50).`
              : "Type the complete selling price for each option."}
          </Text>

          {/* Option toggles */}
          {chart.options.length > 0 ? (
            <>
              <Text style={st.label}>Tap the options you stock</Text>
              <View style={st.chipWrap}>
                {chart.options.map((o) => {
                  const on = chosen.has(o.label.toLowerCase());
                  return (
                    <TouchableOpacity
                      key={o.label}
                      onPress={() => toggleOption(o.label)}
                      style={[st.sizeChip, on && st.chipOn]}
                      testID={`variant-opt-${o.label}`}
                    >
                      <Text style={[st.sizeChipText, on && { color: colors.primaryFg }]}>{o.label}</Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
            </>
          ) : null}

          {/* Custom labels */}
          <Text style={st.label}>{chart.options.length ? "Or add your own label" : "Add your option labels"}</Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <TextInput
              value={customLabel}
              onChangeText={setCustomLabel}
              placeholder="e.g. 42 EU, 8GB / 512GB"
              placeholderTextColor={colors.textMuted}
              style={[st.input, { flex: 1 }]}
              testID="variant-custom-label"
            />
            <TouchableOpacity
              onPress={() => {
                const l = customLabel.trim();
                if (!l || chosen.has(l.toLowerCase())) { setCustomLabel(""); return; }
                toggleOption(l);
                setCustomLabel("");
              }}
              style={st.addBtn}
              testID="variant-custom-add"
            >
              <Feather name="plus" size={16} color={colors.primaryFg} />
            </TouchableOpacity>
          </View>

          {/* Rows */}
          {value.rows.length > 0 ? (
            <>
              <View style={st.rowHead}>
                <Text style={[st.rowHeadCell, { width: 66 }]}>OPTION</Text>
                <Text style={[st.rowHeadCell, { width: 86, textAlign: "center" }]}>STOCK</Text>
                <Text style={[st.rowHeadCell, { width: 86, textAlign: "center" }]}>
                  {value.priceMode === "extra" ? "EXTRA ₹" : "PRICE ₹"}
                </Text>
                <View style={{ width: 28 }} />
              </View>
              {value.rows.map((r, i) => {
                const shown = value.priceMode === "extra"
                  ? (basePrice || 0) + (Number(r.price_extra) || 0)
                  : (Number(r.price_abs) || 0);
                return (
                  <View key={`${r.label}-${i}`} style={st.row}>
                    {/* Fixed width — a flex column collapsed to ~10 px on a
                        narrow phone and printed the price one glyph per line. */}
                    <View style={{ width: 66 }}>
                      <Text style={st.rowLabel} numberOfLines={1}>{r.label}</Text>
                      <Text style={st.rowSell}>₹{Math.round(shown)}</Text>
                    </View>
                    <TextInput
                      value={r.stock}
                      onChangeText={(t) => patchRow(i, { stock: num(t) })}
                      keyboardType="number-pad"
                      style={[st.input, { width: 86, textAlign: "center" }]}
                      testID={`variant-stock-${r.label}`}
                    />
                    <TextInput
                      value={value.priceMode === "extra" ? r.price_extra : r.price_abs}
                      onChangeText={(t) => patchRow(i, value.priceMode === "extra" ? { price_extra: num(t) } : { price_abs: num(t) })}
                      keyboardType="decimal-pad"
                      style={[st.input, { width: 86, textAlign: "center" }]}
                      testID={`variant-price-${r.label}`}
                    />
                    <TouchableOpacity
                      onPress={() => onChange({ ...value, rows: value.rows.filter((_, j) => j !== i) })}
                      style={st.delBtn}
                      testID={`variant-del-${r.label}`}
                    >
                      <Feather name="trash-2" size={14} color="#B91C1C" />
                    </TouchableOpacity>
                  </View>
                );
              })}
              <Text style={st.hint}>
                Options with 0 stock still show on the product page, struck
                through, so customers know you carry that size.
              </Text>
            </>
          ) : null}

          {/* Measurement preview so the vendor can sanity-check the chart */}
          {chart.guide.length > 0 ? (
            <View style={st.guideBox}>
              <Text style={st.guideTitle}>Customers will see this size guide</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                <View>
                  <View style={st.gRow}>
                    {chart.columns.map((c) => <Text key={c} style={[st.gCell, st.gHead]}>{c}</Text>)}
                  </View>
                  {chart.guide.slice(0, 4).map((row, ri) => (
                    <View key={`g${ri}`} style={st.gRow}>
                      {row.map((cell, ci) => <Text key={`g${ri}-${ci}`} style={st.gCell}>{cell}</Text>)}
                    </View>
                  ))}
                </View>
              </ScrollView>
              {chart.guide.length > 4 ? <Text style={st.hint}>+{chart.guide.length - 4} more rows</Text> : null}
            </View>
          ) : null}
        </>
      ) : null}
    </View>
  );
}

const st = StyleSheet.create({
  wrap: {
    marginTop: 14, padding: 12, borderRadius: 14,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted,
  },
  headRow: { flexDirection: "row", alignItems: "flex-start", gap: 8 },
  title: { fontSize: 14, fontWeight: "900", color: colors.textMain },
  hint: { fontSize: 11, color: colors.textMuted, marginTop: 5, lineHeight: 16 },
  label: { fontSize: 11, fontWeight: "900", color: colors.textMuted, letterSpacing: 0.4, marginTop: 14 },
  totalPill: { backgroundColor: colors.primary, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5 },
  totalPillText: { color: colors.primaryFg, fontWeight: "900", fontSize: 11 },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 },
  chip: {
    paddingHorizontal: 11, paddingVertical: 8, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, minHeight: 34,
  },
  chipOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 11.5, fontWeight: "800", color: colors.textMain },
  sizeChip: {
    minWidth: 46, minHeight: 40, paddingHorizontal: 12,
    alignItems: "center", justifyContent: "center", borderRadius: 10,
    borderWidth: 1.5, borderColor: colors.border, backgroundColor: colors.surface,
  },
  sizeChipText: { fontSize: 12.5, fontWeight: "800", color: colors.textMain },
  input: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: 10, paddingHorizontal: 10, paddingVertical: 9,
    fontSize: 13, color: colors.textMain, minHeight: 42,
  },
  addBtn: {
    width: 44, minHeight: 42, borderRadius: 10, backgroundColor: colors.primary,
    alignItems: "center", justifyContent: "center",
  },
  rowHead: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 16, paddingHorizontal: 2 },
  rowHeadCell: { fontSize: 9.5, fontWeight: "900", color: colors.textMuted, letterSpacing: 0.5 },
  row: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8 },
  rowLabel: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  rowSell: { fontSize: 10, color: colors.primary, fontWeight: "800", marginTop: 1 },
  delBtn: { width: 28, height: 42, alignItems: "center", justifyContent: "center" },
  guideBox: {
    marginTop: 16, padding: 10, borderRadius: 12,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  guideTitle: { fontSize: 11, fontWeight: "900", color: colors.textMuted, letterSpacing: 0.4, marginBottom: 8 },
  gRow: { flexDirection: "row" },
  gCell: { minWidth: 82, fontSize: 11, color: colors.textMain, paddingVertical: 6, textAlign: "center" },
  gHead: { fontSize: 9.5, fontWeight: "900", color: colors.textMuted },
});
