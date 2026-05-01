// Reusable SVG charts using react-native-svg (already installed).
// All charts respect device width and follow a clean modern design.
import { useMemo } from "react";
import { View, Text, StyleSheet } from "react-native";
import Svg, {
  Path,
  Circle,
  Line,
  G,
  Defs,
  LinearGradient as SvgLinearGradient,
  Stop,
  Rect,
  Text as SvgText,
} from "react-native-svg";
import { colors } from "./theme";

// ----- Sparkline -----
export function Sparkline({
  data,
  width = 280,
  height = 80,
  strokeColor = "#3DB082",
  fillFrom = "rgba(61,176,130,0.35)",
  fillTo = "rgba(61,176,130,0.0)",
}: {
  data: number[];
  width?: number;
  height?: number;
  strokeColor?: string;
  fillFrom?: string;
  fillTo?: string;
}) {
  const { linePath, areaPath, dotX, dotY } = useMemo(() => {
    if (!data || data.length === 0) return { linePath: "", areaPath: "", dotX: 0, dotY: 0 };
    const max = Math.max(...data, 1);
    const min = Math.min(...data, 0);
    const range = max - min || 1;
    const stepX = data.length > 1 ? width / (data.length - 1) : width;
    const points = data.map((v, i) => {
      const x = i * stepX;
      const y = height - ((v - min) / range) * (height - 8) - 4;
      return [x, y] as [number, number];
    });
    const lp = points.map((p, i) => `${i === 0 ? "M" : "L"} ${p[0]} ${p[1]}`).join(" ");
    const ap = `${lp} L ${points[points.length - 1][0]} ${height} L ${points[0][0]} ${height} Z`;
    const last = points[points.length - 1];
    return { linePath: lp, areaPath: ap, dotX: last[0], dotY: last[1] };
  }, [data, width, height]);

  if (!data || data.length === 0) return <View style={{ width, height }} />;

  return (
    <Svg width={width} height={height}>
      <Defs>
        <SvgLinearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor={fillFrom} />
          <Stop offset="1" stopColor={fillTo} />
        </SvgLinearGradient>
      </Defs>
      <Path d={areaPath} fill="url(#sparkFill)" />
      <Path d={linePath} stroke={strokeColor} strokeWidth={2.5} fill="none" />
      <Circle cx={dotX} cy={dotY} r={5} fill="#fff" stroke={strokeColor} strokeWidth={2.5} />
    </Svg>
  );
}

// ----- Donut Progress -----
export function DonutProgress({
  value,
  max = 100,
  size = 120,
  strokeWidth = 14,
  color = "#3DB082",
  trackColor = "#E5EDEA",
  label,
  sublabel,
}: {
  value: number;
  max?: number;
  size?: number;
  strokeWidth?: number;
  color?: string;
  trackColor?: string;
  label?: string;
  sublabel?: string;
}) {
  const r = (size - strokeWidth) / 2;
  const c = size / 2;
  const circ = 2 * Math.PI * r;
  const pct = Math.max(0, Math.min(1, value / max));
  const dash = circ * pct;

  return (
    <View style={{ width: size, height: size, alignItems: "center", justifyContent: "center" }}>
      <Svg width={size} height={size}>
        <G rotation={-90} origin={`${c},${c}`}>
          <Circle cx={c} cy={c} r={r} stroke={trackColor} strokeWidth={strokeWidth} fill="none" />
          <Circle
            cx={c}
            cy={c}
            r={r}
            stroke={color}
            strokeWidth={strokeWidth}
            fill="none"
            strokeDasharray={`${dash} ${circ - dash}`}
            strokeLinecap="round"
          />
        </G>
      </Svg>
      <View style={styles.donutLabelWrap}>
        <Text style={styles.donutValue}>{label ?? `${Math.round(pct * 100)}%`}</Text>
        {sublabel ? <Text style={styles.donutSub}>{sublabel}</Text> : null}
      </View>
    </View>
  );
}

// ----- Bar Chart (vertical) -----
export function BarChart({
  data,
  labels,
  width = 320,
  height = 160,
  color = "#3DB082",
  showValues = false,
}: {
  data: number[];
  labels?: string[];
  width?: number;
  height?: number;
  color?: string;
  showValues?: boolean;
}) {
  const padX = 20;
  const padTop = showValues ? 22 : 8;
  const padBottom = labels ? 22 : 8;
  const innerW = width - padX * 2;
  const innerH = height - padTop - padBottom;
  const max = Math.max(...data, 1);
  const barGap = 6;
  const barW = (innerW - barGap * (data.length - 1)) / data.length;

  return (
    <Svg width={width} height={height}>
      <Defs>
        <SvgLinearGradient id="barFill" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor={color} stopOpacity={1} />
          <Stop offset="1" stopColor={color} stopOpacity={0.5} />
        </SvgLinearGradient>
      </Defs>
      {data.map((v, i) => {
        const h = (v / max) * innerH;
        const x = padX + i * (barW + barGap);
        const y = padTop + (innerH - h);
        return (
          <G key={i}>
            <Rect x={x} y={y} width={barW} height={h} rx={5} fill="url(#barFill)" />
            {showValues && v > 0 ? (
              <SvgText x={x + barW / 2} y={y - 4} textAnchor="middle" fontSize={10} fontWeight="700" fill={colors.textMain}>
                {v}
              </SvgText>
            ) : null}
            {labels && labels[i] ? (
              <SvgText
                x={x + barW / 2}
                y={height - 6}
                textAnchor="middle"
                fontSize={9}
                fill={colors.textMuted}
              >
                {labels[i]}
              </SvgText>
            ) : null}
          </G>
        );
      })}
      {/* baseline */}
      <Line x1={padX} x2={width - padX} y1={height - padBottom} y2={height - padBottom} stroke="#E5EDEA" strokeWidth={1} />
    </Svg>
  );
}

const styles = StyleSheet.create({
  donutLabelWrap: { position: "absolute", alignItems: "center", justifyContent: "center" },
  donutValue: { fontSize: 22, fontWeight: "800", color: colors.textMain, letterSpacing: -0.5 },
  donutSub: { fontSize: 10, color: colors.textMuted, marginTop: 2, letterSpacing: 1, fontWeight: "700" },
});
