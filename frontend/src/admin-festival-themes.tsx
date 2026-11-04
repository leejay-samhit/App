/**
 * Admin → Branding & Themes → Festival Themes (Oct-2026).
 *
 * Lists the ten festivals as preview cards. All ten are fully designed and
 * can be previewed + applied.
 *
 * Applying a theme only rewrites branding colours — no business logic, user
 * data or permissions are touched.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Alert, Image, Platform, StyleSheet, Text, TouchableOpacity, View,
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { Feather } from "@expo/vector-icons";
import Constants from "expo-constants";
import { api, formatApiError } from "./api";
import { useBrandingActions, type Branding } from "./branding";
import { colors, radii, spacing } from "./theme";

type FestivalCard = {
  id: string;
  name: string;
  subtitle: string;
  icon: any;
  available: boolean;
  swatches: string[];
  colors: Record<string, string>;
  gradient: Record<string, string>;
  decor: Record<string, any>;
};

const API_BASE =
  (process.env.EXPO_PUBLIC_BACKEND_URL as string) ||
  (Constants.expoConfig?.extra as any)?.backendUrl ||
  "";

export function FestivalThemesSection() {
  const { setBranding } = useBrandingActions();
  const [items, setItems] = useState<FestivalCard[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [artwork, setArtwork] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: FestivalCard[]; active_id: string | null }>("/festival-themes");
      setItems(data.items || []);
      setActiveId(data.active_id || null);
    } catch (e) {
      setNotice({ ok: false, text: formatApiError(e) });
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const applyTheme = async (f: FestivalCard) => {
    setBusy(f.id);
    setNotice(null);
    try {
      const { data } = await api.post<Branding>("/admin/festival-theme/apply", { festival_id: f.id });
      setBranding(data);
      setActiveId(f.id);
      setNotice({ ok: true, text: `${f.name} theme is live — open apps pick it up within a minute.` });
    } catch (e) {
      setNotice({ ok: false, text: formatApiError(e) });
    } finally { setBusy(null); }
  };

  const confirmApply = (f: FestivalCard) => {
    if (!f.available) {
      setNotice({ ok: false, text: `The ${f.name} theme isn't ready yet.` });
      return;
    }
    if (Platform.OS === "web") { applyTheme(f); return; }
    Alert.alert(
      `Apply the ${f.name} theme?`,
      "Every user's app will switch to this look. Nothing else changes — orders, wallets and accounts stay exactly as they are.",
      [{ text: "Cancel", style: "cancel" }, { text: "Apply", onPress: () => applyTheme(f) }],
    );
  };

  const restoreDefault = async () => {
    setBusy("__clear__");
    setNotice(null);
    try {
      const { data } = await api.post<Branding>("/admin/festival-theme/clear");
      setBranding(data);
      setActiveId(null);
      setNotice({ ok: true, text: "Back to the standard Slangcart theme." });
    } catch (e) {
      setNotice({ ok: false, text: formatApiError(e) });
    } finally { setBusy(null); }
  };

  const generateArtwork = async (f: FestivalCard) => {
    setBusy(`art-${f.id}`);
    setNotice(null);
    try {
      const { data } = await api.post<{ url: string }>("/admin/festival-theme/artwork", {
        festival_id: f.id, slot: "banner",
      });
      setArtwork((a) => ({ ...a, [f.id]: data.url }));
      setNotice({ ok: true, text: `${f.name} banner artwork generated.` });
      load();
    } catch (e) {
      setNotice({ ok: false, text: formatApiError(e) });
    } finally { setBusy(null); }
  };

  if (loading) {
    return (
      <View style={styles.loading}><ActivityIndicator color={colors.primary} /></View>
    );
  }

  return (
    <View testID="festival-themes-section">
      <Text style={styles.helper}>
        One tap re-skins the whole app — home, shop, cart, wallet, chat, vendor
        screens and the tab bar. Only the look changes; orders, payments and
        accounts are untouched.
      </Text>

      {notice ? (
        <View style={[styles.notice, notice.ok ? styles.noticeOk : styles.noticeErr]} testID="festival-notice">
          <Feather name={notice.ok ? "check-circle" : "alert-triangle"} size={14}
            color={notice.ok ? colors.success : colors.error} />
          <Text style={[styles.noticeText, { color: notice.ok ? colors.success : colors.error }]}>{notice.text}</Text>
        </View>
      ) : null}

      <View style={styles.activeRow}>
        <Feather name={activeId ? "sun" : "circle"} size={14} color={activeId ? colors.accent : colors.textMuted} />
        <Text style={styles.activeText} numberOfLines={1}>
          Active: {activeId ? (items.find((i) => i.id === activeId)?.name || activeId) : "Standard Slangcart theme"}
        </Text>
        {activeId ? (
          <TouchableOpacity onPress={restoreDefault} style={styles.restoreBtn} testID="festival-restore">
            {busy === "__clear__"
              ? <ActivityIndicator size="small" color={colors.primary} />
              : <Text style={styles.restoreText}>Restore default</Text>}
          </TouchableOpacity>
        ) : null}
      </View>

      {items.map((f) => {
        const isActive = f.id === activeId;
        const g = f.gradient || {};
        return (
          <View key={f.id} style={[styles.card, isActive && styles.cardActive]} testID={`festival-card-${f.id}`}>
            <LinearGradient
              colors={[g.start || "#2B2B33", g.middle || "#3F3F4A", g.end || "#55555F"]}
              start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}
              style={styles.cardArt}
            >
              {artwork[f.id] && API_BASE ? (
                <Image source={{ uri: `${API_BASE.replace(/\/$/, "")}${artwork[f.id]}` }}
                  style={styles.cardArtImg} resizeMode="cover" />
              ) : null}
              <View style={styles.cardArtTop}>
                <Feather name={f.icon} size={16} color={g.glow || "#FFD479"} />
                {isActive ? (
                  <View style={styles.liveChip}><Text style={styles.liveChipText}>LIVE</Text></View>
                ) : !f.available ? (
                  <View style={styles.soonChip}><Text style={styles.soonChipText}>COMING SOON</Text></View>
                ) : null}
              </View>
              <Text style={[styles.cardArtName, { color: g.glow || "#FFD479" }]} numberOfLines={1}>{f.name}</Text>
            </LinearGradient>

            <View style={styles.cardBody}>
              <Text style={styles.cardSub} numberOfLines={2}>{f.subtitle}</Text>
              <View style={styles.swatchRow}>
                {(f.swatches || []).map((c, i) => (
                  <View key={i} style={[styles.swatch, { backgroundColor: c }]} />
                ))}
              </View>

              <View style={styles.btnRow}>
                <TouchableOpacity
                  onPress={() => setPreview((p) => (p === f.id ? null : f.id))}
                  style={styles.previewBtn}
                  testID={`festival-preview-${f.id}`}
                >
                  <Feather name={preview === f.id ? "eye-off" : "eye"} size={14} color={colors.textMain} />
                  <Text style={styles.previewBtnText}>
                    {preview === f.id ? "Hide Preview" : "Preview Theme"}
                  </Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => confirmApply(f)}
                  disabled={!f.available || busy === f.id || isActive}
                  style={[styles.applyBtn, (!f.available || isActive) && { opacity: 0.45 }]}
                  testID={`festival-apply-${f.id}`}
                >
                  {busy === f.id
                    ? <ActivityIndicator size="small" color={colors.primaryFg} />
                    : <>
                        <Feather name={isActive ? "check" : "zap"} size={14} color={colors.primaryFg} />
                        <Text style={styles.applyBtnText}>{isActive ? "Applied" : "Apply Theme"}</Text>
                      </>}
                </TouchableOpacity>
              </View>

              {preview === f.id ? (
                <View style={styles.previewWrap} testID={`festival-preview-panel-${f.id}`}>
                  <Text style={styles.previewCaption}>
                    How the app will look{f.available ? "" : " once this theme ships"}
                  </Text>
                  <ThemePreview f={f} />
                </View>
              ) : null}

              {f.available ? (
                <TouchableOpacity onPress={() => generateArtwork(f)} disabled={busy === `art-${f.id}`}
                  style={styles.artBtn} testID={`festival-artwork-${f.id}`}>
                  {busy === `art-${f.id}`
                    ? <ActivityIndicator size="small" color={colors.textMuted} />
                    : <Feather name="image" size={13} color={colors.textMuted} />}
                  <Text style={styles.artBtnText}>
                    {busy === `art-${f.id}` ? "Generating artwork…" : "Generate AI banner artwork"}
                  </Text>
                </TouchableOpacity>
              ) : null}
            </View>
          </View>
        );
      })}
    </View>
  );
}

/** A miniature of the real app chrome, painted in the festival's palette. */
function ThemePreview({ f }: { f: FestivalCard }) {  const c = f.colors || {};
  const g = f.gradient || {};
  const bg = c.background || colors.background;
  const surface = c.surface || colors.surface;
  const primary = c.primary || colors.primary;
  const accent = c.accent || colors.accent;
  const textMain = c.textMain || colors.textMain;
  const textMuted = c.textMuted || colors.textMuted;
  const border = c.border || colors.border;

  return (
    <View>
      <View style={[pv.phone, { backgroundColor: bg, borderColor: border }]}>
        <View style={[pv.appBar, { backgroundColor: primary }]}>
          <Text style={[pv.appBarText, { color: c.primaryFg || "#fff" }]}>Slangcart</Text>
        </View>

        <LinearGradient colors={[g.start || "#190A33", g.middle || "#3B1178", g.end || "#7C2D12"]}
          start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={pv.hero}>
          <Text style={[pv.heroTitle, { color: g.glow || "#FFD479" }]}>
            {f.decor?.banner_title || f.name}
          </Text>
          <Text style={pv.heroSub}>{f.decor?.banner_subtitle || `Celebrate ${f.name} with us`}</Text>
        </LinearGradient>

        <View style={pv.row}>
          {[0, 1].map((i) => (
            <View key={i} style={[pv.product, { backgroundColor: surface, borderColor: border }]}>
              <View style={[pv.productImg, { backgroundColor: c.surfaceMuted || colors.surfaceMuted }]} />
              <Text style={[pv.productName, { color: textMain }]}>Festive item</Text>
              <Text style={[pv.productPrice, { color: primary }]}>₹1,299</Text>
              <View style={[pv.cta, { backgroundColor: accent }]}>
                <Text style={[pv.ctaText, { color: c.accentFg || "#2A1500" }]}>Buy now</Text>
              </View>
            </View>
          ))}
        </View>

        <View style={[pv.listCard, { backgroundColor: surface, borderColor: border }]}>
          <Text style={[pv.listTitle, { color: textMain }]}>Wallet balance</Text>
          <Text style={[pv.listSub, { color: textMuted }]}>Cashback credited on delivery</Text>
        </View>

        <View style={[pv.tabBar, { backgroundColor: surface, borderColor: border }]}>
          {["home", "shopping-bag", "briefcase", "user"].map((n, i) => (
            <Feather key={n} name={n as any} size={16} color={i === 1 ? primary : textMuted} />
          ))}
        </View>
      </View>
      {!f.available ? (
        <Text style={[styles.helper, { marginTop: 10 }]}>
          This is the planned palette — {f.name} artwork and decorations are
          still being finished.
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  loading: { paddingVertical: 24, alignItems: "center" },
  helper: { color: colors.textMuted, fontSize: 12, lineHeight: 18, marginBottom: 10 },
  notice: { flexDirection: "row", alignItems: "center", gap: 8, padding: 10, borderRadius: 10, borderWidth: 1, marginBottom: 10 },
  noticeOk: { backgroundColor: "#E8F5EE", borderColor: "#2E7D5233" },
  noticeErr: { backgroundColor: "#FDECEA", borderColor: "#B3261E33" },
  noticeText: { flex: 1, fontSize: 12, fontWeight: "700" },
  activeRow: {
    flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 12,
    paddingVertical: 10, paddingHorizontal: 12, borderRadius: 12,
    backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border,
  },
  activeText: { flex: 1, fontSize: 12, fontWeight: "800", color: colors.textMain },
  restoreBtn: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  restoreText: { fontSize: 11, fontWeight: "800", color: colors.primary },

  card: { borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, overflow: "hidden", marginBottom: 14 },
  cardActive: { borderColor: colors.accent, borderWidth: 2 },
  cardArt: { height: 92, padding: 12, justifyContent: "space-between" },
  cardArtImg: { ...StyleSheet.absoluteFillObject, opacity: 0.6 },
  cardArtTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  cardArtName: { fontSize: 18, fontWeight: "900" },
  liveChip: { backgroundColor: "#FFFFFFEE", borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  liveChipText: { fontSize: 9, fontWeight: "900", color: "#15803D", letterSpacing: 0.5 },
  soonChip: { backgroundColor: "#00000055", borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  soonChipText: { fontSize: 9, fontWeight: "900", color: "#FFFFFFCC", letterSpacing: 0.5 },

  cardBody: { padding: spacing.cardPad, gap: 10 },
  cardSub: { fontSize: 12, color: colors.textMuted, lineHeight: 17 },
  swatchRow: { flexDirection: "row", gap: 6 },
  swatch: { width: 26, height: 26, borderRadius: 8, borderWidth: 1, borderColor: colors.border },
  btnRow: { flexDirection: "row", gap: 8 },
  previewBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    minHeight: 44, borderRadius: radii.button, backgroundColor: colors.surfaceMuted,
    borderWidth: 1, borderColor: colors.border,
  },
  previewBtnText: { fontSize: 12, fontWeight: "800", color: colors.textMain },
  applyBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    minHeight: 44, borderRadius: radii.button, backgroundColor: colors.primary,
  },
  applyBtnText: { fontSize: 12, fontWeight: "800", color: colors.primaryFg },
  artBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, minHeight: 36 },
  artBtnText: { fontSize: 11, fontWeight: "700", color: colors.textMuted },

  previewWrap: { gap: 8, paddingTop: 4 },
  previewCaption: { fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 0.3 },
});

const pv = StyleSheet.create({
  phone: { borderRadius: 18, borderWidth: 1, overflow: "hidden" },
  appBar: { paddingVertical: 10, alignItems: "center" },
  appBarText: { fontSize: 13, fontWeight: "900", letterSpacing: 0.4 },
  hero: { margin: 10, borderRadius: 14, padding: 14 },
  heroTitle: { fontSize: 16, fontWeight: "900" },
  heroSub: { color: "#F3E8FF", fontSize: 11, fontWeight: "600", marginTop: 2 },
  row: { flexDirection: "row", gap: 10, paddingHorizontal: 10 },
  product: { flex: 1, borderRadius: 12, borderWidth: 1, padding: 8, gap: 4 },
  productImg: { height: 54, borderRadius: 8 },
  productName: { fontSize: 11, fontWeight: "700" },
  productPrice: { fontSize: 12, fontWeight: "900" },
  cta: { borderRadius: 999, alignItems: "center", paddingVertical: 6, marginTop: 2 },
  ctaText: { fontSize: 10, fontWeight: "900" },
  listCard: { margin: 10, borderRadius: 12, borderWidth: 1, padding: 10 },
  listTitle: { fontSize: 12, fontWeight: "800" },
  listSub: { fontSize: 10, marginTop: 2 },
  tabBar: { flexDirection: "row", justifyContent: "space-around", paddingVertical: 10, borderTopWidth: 1 },
});
