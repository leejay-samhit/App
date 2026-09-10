/**
 * Shop / Services tab.
 *
 * Route responsibilities:
 *   • /shop      → renders <ShopHome/> (dedicated component with its own
 *                  header, banner, product & category sections).
 *   • /services  → provider-discovery UI (kept in this file so that
 *                  services.tsx can re-export the default component).
 *
 * NOTE (Jun 2026 cleanup): the legacy inline shop grid + interest / fav
 * buttons that lived here were dead code — the shop route short-circuits
 * to <ShopHome/> long before they render. ~700 lines removed. If you need
 * to bring anything back, check git history.
 */
import { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Image,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
  Alert,
  TextInput,
  Modal,
  Linking,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useFocusEffect, useRouter, usePathname } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { ShopHome } from "../../src/shop-home";
import { getCurrentCoords, formatDistance, formatActiveAgo } from "../../src/location";
import { useDoubleTapExit } from "../../src/use-double-tap-exit";

type ServiceCategory = {
  id: string;
  name: string;
  slug: string;
  icon: string;
  color: string;
  sort_order: number;
  active: boolean;
  provider_count: number;
};
type ServiceProvider = {
  id: string;
  name: string;
  phone?: string;
  email: string;
  referral_code: string;
  service_name: string;
  service_category: string;
  category_id?: string | null;
  service_languages?: string[];
  service_pincode: string;
  service_charge: number;
  service_description?: string;
  distance_km?: number | null;
  is_active?: boolean;
  location_updated_at?: string | null;
  availability_status?: "available" | "busy" | "offline" | null;
  availability_updated_at?: string | null;
  profile_image?: string | null;
};
type Mode = "shop" | "services";

const LANG_LABELS: Record<string, string> = { en: "English", te: "Telugu", hi: "Hindi", ta: "Tamil" };
const LANG_ORDER = ["en", "te", "hi", "ta"];

export default function ShopScreen() {
  const router = useRouter();
  useDoubleTapExit();
  const pathname = usePathname();
  const lockedMode: Mode = pathname && pathname.includes("/services") ? "services" : "shop";
  const [mode, setMode] = useState<Mode>(lockedMode);
  useEffect(() => { setMode(lockedMode); }, [lockedMode]);

  // Cart count shown by <ShopHome/> — updated on focus.
  const [cartCount, setCartCount] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  // ---- Services state ----
  const [services, setServices] = useState<ServiceProvider[]>([]);
  const [servicesLoading, setServicesLoading] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [pincodeQ, setPincodeQ] = useState("");
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [subcategoryId, setSubcategoryId] = useState<string | null>(null);
  const [subcategories, setSubcategories] = useState<{ id: string; name: string; icon?: string }[]>([]);
  const [languageQ, setLanguageQ] = useState<string | null>(null);
  const [langModalOpen, setLangModalOpen] = useState(false);
  const [myCoords, setMyCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [locating, setLocating] = useState(false);
  const [categories, setCategories] = useState<ServiceCategory[]>([]);
  const [contactOf, setContactOf] = useState<ServiceProvider | null>(null);
  const [bookingId, setBookingId] = useState<string | null>(null);

  // Lightweight cart-count fetch for shop mode. Guest / 401 is silently ignored.
  const loadCartCount = useCallback(async () => {
    try {
      const cart = await api.get<any>("/cart");
      const cItems = Array.isArray(cart.data) ? cart.data : (cart.data?.items || []);
      setCartCount(cItems.reduce((s: number, i: any) => s + (i.qty || i.quantity || 0), 0));
    } catch {
      /* cart may 401 for guests */
    } finally {
      setRefreshing(false);
    }
  }, []);

  const loadServices = useCallback(async () => {
    setServicesLoading(true);
    try {
      const params: Record<string, string> = {};
      if (searchQ) params.q = searchQ;
      if (pincodeQ) params.pincode = pincodeQ;
      if (categoryId) params.category_id = categoryId;
      if (subcategoryId) params.subcategory_id = subcategoryId;
      if (languageQ) params.language = languageQ;
      if (myCoords) {
        params.lat = String(myCoords.lat);
        params.lng = String(myCoords.lng);
      }
      const { data } = await api.get<{ items: ServiceProvider[] }>("/services", { params });
      setServices(data.items || []);
      const cats = await api.get<{ categories: ServiceCategory[] }>("/services/categories");
      setCategories(cats.data.categories || []);
    } catch (e) {
      console.warn(e);
    } finally {
      setServicesLoading(false);
      setRefreshing(false);
    }
  }, [searchQ, pincodeQ, categoryId, subcategoryId, languageQ, myCoords]);

  const useMyLocation = useCallback(async () => {
    if (myCoords) {
      setMyCoords(null);
      return;
    }
    setLocating(true);
    try {
      const c = await getCurrentCoords();
      if (!c) {
        Alert.alert(
          "Location unavailable",
          Platform.OS === "web"
            ? "Your browser blocked location access. Allow it in the address-bar lock icon and try again."
            : "Permission denied or GPS off. Enable Location Services and try again.",
        );
        return;
      }
      setMyCoords({ lat: c.lat, lng: c.lng });
      try {
        await api.post("/users/me/location", {
          latitude: c.lat,
          longitude: c.lng,
          accuracy_m: c.accuracy_m ?? null,
        });
      } catch {
        // non-fatal
      }
    } finally {
      setLocating(false);
    }
  }, [myCoords]);

  useFocusEffect(useCallback(() => {
    if (mode === "shop") loadCartCount();
    else loadServices();
  }, [mode, loadCartCount, loadServices]));

  // Load subcategories when parent category changes.
  useEffect(() => {
    if (!categoryId) {
      setSubcategories([]); setSubcategoryId(null); return;
    }
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get<{ items: { id: string; name: string; icon?: string }[] }>(
          `/service-subcategories?parent_id=${encodeURIComponent(categoryId)}`,
        );
        if (!cancelled) setSubcategories(data.items || []);
      } catch {
        if (!cancelled) setSubcategories([]);
      }
    })();
    setSubcategoryId(null);
  }, [categoryId]);

  // Services debounce on filter change.
  useEffect(() => {
    if (mode === "services") {
      const t = setTimeout(loadServices, 300);
      return () => clearTimeout(t);
    }
  }, [searchQ, pincodeQ, categoryId, subcategoryId, languageQ, myCoords, mode, loadServices]);

  const bookService = async (provider: ServiceProvider) => {
    Alert.alert(
      `Book ${provider.service_name}?`,
      `${provider.name} • ₹${provider.service_charge} will be deducted from your wallet.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Book now",
          onPress: async () => {
            setBookingId(provider.id);
            try {
              await api.post(`/services/${provider.id}/book`, { notes: null });
              Alert.alert("Booked", `Your booking is confirmed. ${provider.name} has been notified.`);
              setContactOf(null);
            } catch (e) {
              Alert.alert("Booking failed", formatApiError(e));
            } finally {
              setBookingId(null);
            }
          },
        },
      ],
    );
  };

  const callOrCopy = (phone?: string) => {
    if (!phone) return;
    const url = `tel:${phone}`;
    Linking.openURL(url).catch(() => Alert.alert("Phone", phone));
  };

  // ============ Shop Home Screen ============
  // The /shop route is fully owned by <ShopHome/> — this component only
  // supplies the up-to-date cart badge.
  if (mode === "shop") {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <ShopHome cartCount={cartCount} wishlistCount={0} />
      </SafeAreaView>
    );
  }

  // ============ Services mode ============
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setRefreshing(true); loadServices(); }}
          />
        }
        keyboardShouldPersistTaps="handled"
        stickyHeaderIndices={[0]}
      >
        {/* Pinned header — title, filters and the "near me" toggle stay put
            while the category grid scrolls under them (owner request:
            near-me results must sit ABOVE Browse by category, locked). */}
        <View style={styles.stickyTop}>
          <View style={styles.topHeader}>
            <View style={styles.servicesTitleWrap}>
              <Text style={styles.topHeaderEyebrow}>SERVICES</Text>
              <Text style={styles.topHeaderTitle}>Find local talent</Text>
            </View>
          </View>

          {/* Filters */}
          <View style={styles.filterRow}>
            <View style={styles.searchBox}>
              <Feather name="search" size={14} color={colors.textMuted} />
              <TextInput
                style={styles.searchInput}
                placeholder="Service or name"
                placeholderTextColor={colors.textMuted}
                value={searchQ}
                onChangeText={setSearchQ}
              />
            </View>
            <View style={[styles.searchBox, { width: 100 }]}>
              <Feather name="map-pin" size={14} color={colors.textMuted} />
              <TextInput
                style={styles.searchInput}
                placeholder="Pincode"
                placeholderTextColor={colors.textMuted}
                value={pincodeQ}
                onChangeText={setPincodeQ}
                keyboardType="numeric"
                maxLength={6}
              />
            </View>
          </View>

          <TouchableOpacity
            onPress={useMyLocation}
            disabled={locating}
            style={[styles.locBtn, myCoords && styles.locBtnActive]}
            testID="services-use-location"
          >
            {locating ? (
              <ActivityIndicator size="small" color={myCoords ? colors.primaryFg : colors.primary} />
            ) : (
              <Feather name={myCoords ? "navigation" : "navigation-2"} size={15} color={myCoords ? colors.primaryFg : colors.primary} />
            )}
            <View style={{ flex: 1 }}>
              <Text style={[styles.locBtnText, myCoords && styles.locBtnTextActive]}>
                {myCoords ? "Showing nearby first" : "Use my location"}
              </Text>
              <Text style={[styles.locBtnHint, myCoords && { color: "rgba(255,255,255,0.85)" }]}>
                {myCoords ? "Tap to clear and see everyone" : "Nearest service providers first"}
              </Text>
            </View>
            <Feather
              name={myCoords ? "x" : "chevron-right"}
              size={15}
              color={myCoords ? colors.primaryFg : colors.textMuted}
            />
          </TouchableOpacity>
        </View>

        {categories.length > 0 && (
          <View style={styles.categoryGridSection}>
            <View style={styles.sectionHeaderRow}>
              <Text style={styles.sectionTitle}>Browse by category</Text>
              {categoryId ? (
                <TouchableOpacity onPress={() => setCategoryId(null)}>
                  <Text style={styles.clearLink}>Clear</Text>
                </TouchableOpacity>
              ) : null}
            </View>
            <View style={styles.categoryGrid}>
              {categories.map((c) => {
                const sel = categoryId === c.id;
                return (
                  <TouchableOpacity
                    key={c.id}
                    style={[
                      styles.catTile,
                      sel ? { borderColor: c.color, backgroundColor: c.color + "15" } : null,
                    ]}
                    onPress={() => setCategoryId(sel ? null : c.id)}
                    activeOpacity={0.7}
                  >
                    <View style={[styles.catIconWrap, { backgroundColor: c.color + "20" }]}>
                      <Feather name={c.icon as any} size={22} color={c.color} />
                    </View>
                    <Text style={styles.catTileText} numberOfLines={2}>{c.name}</Text>
                    {c.provider_count > 0 ? (
                      <View style={[styles.catCountPill, { backgroundColor: c.color }]}>
                        <Text style={styles.catCountText}>{c.provider_count}</Text>
                      </View>
                    ) : null}
                  </TouchableOpacity>
                );
              })}
            </View>
          </View>
        )}

        <Modal visible={langModalOpen} transparent animationType="slide" onRequestClose={() => setLangModalOpen(false)}>
          <View style={styles.langModalOverlay}>
            <TouchableOpacity style={{ flex: 1 }} activeOpacity={1} onPress={() => setLangModalOpen(false)} />
            <View style={styles.langModalSheet}>
              <View style={styles.langModalHandle} />
              <Text style={styles.langModalTitle}>Filter by language</Text>
              <Text style={styles.langModalSub}>Show service providers who speak…</Text>

              <TouchableOpacity
                style={[styles.langOptionRow, !languageQ && styles.langOptionRowActive]}
                onPress={() => { setLanguageQ(null); setLangModalOpen(false); }}
              >
                <View style={styles.langOptionIconWrap}><Feather name="globe" size={18} color={colors.primary} /></View>
                <Text style={[styles.langOptionText, !languageQ && styles.langOptionTextActive]}>All languages</Text>
                {!languageQ && <Feather name="check" size={18} color={colors.primary} />}
              </TouchableOpacity>

              {LANG_ORDER.map((code) => {
                const active = languageQ === code;
                return (
                  <TouchableOpacity
                    key={code}
                    style={[styles.langOptionRow, active && styles.langOptionRowActive]}
                    onPress={() => { setLanguageQ(code); setLangModalOpen(false); }}
                    testID={`lang-option-${code}`}
                  >
                    <View style={styles.langOptionIconWrap}>
                      <Text style={{ fontSize: 12, fontWeight: "900", color: colors.primary }}>{code.toUpperCase()}</Text>
                    </View>
                    <Text style={[styles.langOptionText, active && styles.langOptionTextActive]}>{LANG_LABELS[code]}</Text>
                    {active && <Feather name="check" size={18} color={colors.primary} />}
                  </TouchableOpacity>
                );
              })}

              <TouchableOpacity
                style={styles.langModalClose}
                onPress={() => setLangModalOpen(false)}
              >
                <Text style={styles.langModalCloseText}>Close</Text>
              </TouchableOpacity>
            </View>
          </View>
        </Modal>

        {/* Provider list modal */}
        <Modal
          visible={!!categoryId}
          transparent
          animationType="slide"
          onRequestClose={() => setCategoryId(null)}
        >
          <View style={styles.providerSheetOverlay}>
            <View style={styles.providerSheetContainer}>
              <View style={styles.providerSheetHeader}>
                <TouchableOpacity onPress={() => setCategoryId(null)} style={styles.providerSheetBack} testID="provider-sheet-close">
                  <Feather name="arrow-left" size={20} color={colors.textMain} />
                </TouchableOpacity>
                <View style={{ flex: 1 }}>
                  <Text style={styles.providerSheetEyebrow}>SERVICE PROVIDERS</Text>
                  <Text style={styles.providerSheetTitle} numberOfLines={1}>
                    {categories.find((c) => c.id === categoryId)?.name || "Providers"}
                  </Text>
                </View>
                <TouchableOpacity
                  onPress={() => setLangModalOpen(true)}
                  style={[styles.cartIconBtn, languageQ && { backgroundColor: colors.brand100, borderColor: colors.primary }, { width: 36, height: 36, borderRadius: 18 }]}
                  hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
                >
                  <Feather name="globe" size={16} color={languageQ ? colors.primary : colors.textMain} />
                </TouchableOpacity>
              </View>

              {subcategories.length > 0 ? (
                <View style={{ backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border }}>
                  <ScrollView
                    horizontal
                    showsHorizontalScrollIndicator={false}
                    contentContainerStyle={{ paddingHorizontal: 14, paddingVertical: 10, gap: 6 }}
                  >
                    <TouchableOpacity
                      onPress={() => setSubcategoryId(null)}
                      style={[styles.subChip, subcategoryId === null && styles.subChipOn]}
                      testID="subchip-all"
                    >
                      <Text style={[styles.subChipText, subcategoryId === null && { color: "#fff" }]}>All</Text>
                    </TouchableOpacity>
                    {subcategories.map((s) => {
                      const on = subcategoryId === s.id;
                      return (
                        <TouchableOpacity
                          key={s.id}
                          onPress={() => setSubcategoryId(on ? null : s.id)}
                          style={[styles.subChip, on && styles.subChipOn]}
                          testID={`subchip-${s.id}`}
                        >
                          {s.icon ? <Feather name={s.icon as any} size={12} color={on ? "#fff" : colors.textMain} /> : null}
                          <Text style={[styles.subChipText, on && { color: "#fff" }]}>
                            {s.icon ? "  " : ""}{s.name}
                          </Text>
                        </TouchableOpacity>
                      );
                    })}
                  </ScrollView>
                </View>
              ) : null}

              <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 32 }}>
                {servicesLoading && services.length === 0 ? (
                  <View style={[styles.center, { paddingVertical: 40 }]}>
                    <ActivityIndicator color={colors.primary} />
                  </View>
                ) : services.length === 0 ? (
                  <View style={styles.emptyCard}>
                    <Feather name="briefcase" size={28} color={colors.textMuted} />
                    <Text style={styles.emptyText}>No service providers found.</Text>
                    <Text style={styles.emptySubtext}>Try a different pincode or language — or be the first to list yours!</Text>
                  </View>
                ) : (
                  services.map((s) => (
                    <TouchableOpacity
                      key={s.id}
                      style={styles.serviceCard}
                      onPress={() => router.push(`/services/${s.id}`)}
                      testID={`service-card-${s.id}`}
                    >
                      <View style={styles.serviceAvatar}>
                        {s.profile_image ? (
                          <Image
                            source={{ uri: s.profile_image }}
                            style={{ width: "100%", height: "100%" }}
                            resizeMode="cover"
                          />
                        ) : (
                          <Text style={styles.serviceAvatarText}>{(s.name || "?")[0].toUpperCase()}</Text>
                        )}
                      </View>
                      <View style={{ flex: 1 }}>
                        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                          {(() => {
                            const av = s.availability_status || "available";
                            const dotBg = av === "available" ? "#16A34A" : av === "busy" ? "#F59E0B" : "#9CA3AF";
                            return (
                              <View
                                style={{
                                  width: 9, height: 9, borderRadius: 5,
                                  backgroundColor: dotBg,
                                  borderWidth: 1.5, borderColor: "#fff",
                                }}
                              />
                            );
                          })()}
                          <Text style={styles.serviceName} numberOfLines={1}>{s.name}</Text>
                          {s.is_active ? (
                            <View style={styles.activeDot}>
                              <View style={styles.activeDotInner} />
                              <Text style={styles.activeDotText}>LIVE</Text>
                            </View>
                          ) : null}
                        </View>
                        <Text style={styles.serviceTitle} numberOfLines={1}>{s.service_name}</Text>
                        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4, flexWrap: "wrap" }}>
                          <View style={styles.tag}><Text style={styles.tagText}>{s.service_category}</Text></View>
                          <View style={styles.tag}>
                            <Feather name="map-pin" size={10} color={colors.textMuted} />
                            <Text style={styles.tagText}> {s.service_pincode}</Text>
                            {s.distance_km != null ? (
                              <>
                                <Text style={[styles.tagText, { color: colors.textMuted, marginHorizontal: 2 }]}>·</Text>
                                <Feather name="navigation" size={10} color="#047857" />
                                <Text style={[styles.tagText, { color: "#047857", fontWeight: "800" }]}> {formatDistance(s.distance_km)}</Text>
                              </>
                            ) : null}
                          </View>
                          {(s.service_languages || []).map((lc) => (
                            <View key={lc} style={[styles.tag, { backgroundColor: "#EEF2FF", borderColor: "#C7D2FE" }]}>
                              <Feather name="globe" size={9} color="#3730A3" />
                              <Text style={[styles.tagText, { color: "#3730A3" }]}> {LANG_LABELS[lc] || lc}</Text>
                            </View>
                          ))}
                        </View>
                        {s.is_active && s.location_updated_at ? (
                          <Text style={styles.activeAgo}>{formatActiveAgo(s.location_updated_at)}</Text>
                        ) : null}
                      </View>
                      <View style={{ alignItems: "flex-end" }}>
                        <Text style={styles.servicePrice}>{formatINR(s.service_charge || 0)}</Text>
                        <Feather name="chevron-right" size={18} color={colors.textMuted} />
                      </View>
                    </TouchableOpacity>
                  ))
                )}
              </ScrollView>
            </View>
          </View>
        </Modal>
      </ScrollView>

      {/* Contact / book modal */}
      <Modal visible={!!contactOf} transparent animationType="slide" onRequestClose={() => setContactOf(null)}>
        <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setContactOf(null)}>
          <TouchableOpacity activeOpacity={1} style={styles.modalSheet} onPress={() => {}}>
            {contactOf && (
              <>
                <View style={styles.modalHandle} />
                <Text style={styles.modalTitle}>{contactOf.name}</Text>
                <Text style={styles.modalSubtitle}>{contactOf.service_name} · {contactOf.service_category}</Text>
                {contactOf.service_description ? <Text style={styles.modalDesc}>{contactOf.service_description}</Text> : null}

                <View style={styles.modalRow}>
                  <Feather name="phone" size={14} color={colors.textMuted} />
                  <Text style={styles.modalRowText}>{contactOf.phone || "—"}</Text>
                </View>
                <View style={styles.modalRow}>
                  <Feather name="mail" size={14} color={colors.textMuted} />
                  <Text style={styles.modalRowText}>{contactOf.email}</Text>
                </View>
                <View style={styles.modalRow}>
                  <Feather name="hash" size={14} color={colors.textMuted} />
                  <Text style={styles.modalRowText}>Ref: {contactOf.referral_code}</Text>
                </View>
                <View style={styles.modalRow}>
                  <Feather name="map-pin" size={14} color={colors.textMuted} />
                  <Text style={styles.modalRowText}>Pincode {contactOf.service_pincode}</Text>
                </View>
                <View style={[styles.modalRow, { marginBottom: 14 }]}>
                  <Feather name="tag" size={14} color={colors.textMuted} />
                  <Text style={[styles.modalRowText, { fontWeight: "800", color: colors.primary }]}>{formatINR(contactOf.service_charge || 0)}</Text>
                </View>

                <View style={{ flexDirection: "row", gap: 10 }}>
                  <TouchableOpacity style={[styles.modalBtn, styles.modalBtnGhost]} onPress={() => callOrCopy(contactOf.phone)}>
                    <Feather name="phone" size={14} color={colors.primary} />
                    <Text style={[styles.modalBtnText, { color: colors.primary }]}>Call</Text>
                  </TouchableOpacity>
                  <TouchableOpacity style={[styles.modalBtn, styles.modalBtnPrimary, bookingId === contactOf.id && { opacity: 0.6 }]} onPress={() => bookService(contactOf)} disabled={bookingId === contactOf.id}>
                    <Feather name="check-circle" size={14} color="#fff" />
                    <Text style={[styles.modalBtnText, { color: "#fff" }]}>{bookingId === contactOf.id ? "Booking..." : "Book & Pay"}</Text>
                  </TouchableOpacity>
                </View>
              </>
            )}
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  container: { paddingHorizontal: 12, paddingTop: spacing.screen, paddingBottom: 60 },

  // The pinned services header (title + filters + near-me). Sticky, so it
  // never scrolls away and the near-me toggle always sits above the
  // category grid.
  stickyTop: {
    backgroundColor: colors.background,
    borderBottomWidth: 1,
    borderBottomColor: colors.border + "66",
    paddingBottom: 4,
    marginBottom: 12,
  },

  topHeader: {
    width: "100%",
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingTop: 10,
    paddingBottom: 12,
    backgroundColor: colors.background,
  },
  servicesTitleWrap: { flex: 1, minWidth: 0, marginRight: 12 },
  topHeaderEyebrow: { fontSize: 10, letterSpacing: 1.6, color: colors.textMuted, fontWeight: "800" },
  topHeaderTitle: { fontSize: 22, fontWeight: "900", color: colors.textMain, letterSpacing: -0.6, marginTop: 2 },

  // Language picker modal sheet
  langModalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "flex-end" },
  langModalSheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 28, borderTopRightRadius: 28,
    paddingHorizontal: 20, paddingTop: 12, paddingBottom: 28,
  },
  langModalHandle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginBottom: 14 },
  langModalTitle: { fontSize: 18, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4 },
  langModalSub: { fontSize: 12, color: colors.textMuted, marginTop: 4, marginBottom: 14 },
  langOptionRow: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingVertical: 12, paddingHorizontal: 12,
    borderRadius: 14,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
    marginBottom: 8,
  },
  langOptionRowActive: { backgroundColor: colors.brand100, borderColor: colors.primary },
  langOptionIconWrap: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.brand100,
    alignItems: "center", justifyContent: "center",
  },
  langOptionText: { flex: 1, fontSize: 14, fontWeight: "700", color: colors.textMain },
  langOptionTextActive: { color: colors.primary },
  langModalClose: {
    marginTop: 8, paddingVertical: 12,
    borderRadius: 12, alignItems: "center",
    backgroundColor: colors.surfaceMuted,
  },
  langModalCloseText: { color: colors.textMain, fontWeight: "800", fontSize: 14 },

  // Provider sheet
  providerSheetOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)" },
  providerSheetContainer: {
    flex: 1, marginTop: 60,
    backgroundColor: colors.background,
    borderTopLeftRadius: 24, borderTopRightRadius: 24,
    overflow: "hidden",
  },
  providerSheetHeader: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 16, paddingTop: 16, paddingBottom: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  providerSheetBack: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.surfaceMuted,
    alignItems: "center", justifyContent: "center",
  },
  providerSheetEyebrow: { fontSize: 9, letterSpacing: 1.4, color: colors.textMuted, fontWeight: "800" },
  providerSheetTitle: { fontSize: 17, fontWeight: "900", color: colors.textMain, letterSpacing: -0.4, marginTop: 1 },
  cartIconBtn: {
    width: 52,
    height: 52,
    marginLeft: 12,
    flexShrink: 0,
    borderRadius: 18,
    backgroundColor: colors.primary,
    alignItems: "center",
    justifyContent: "center",
    ...Platform.select({
      ios: {
        shadowColor: colors.primary,
        shadowOpacity: 0.18,
        shadowRadius: 6,
        shadowOffset: { width: 0, height: 2 },
      },
      android: { elevation: 2 },
      default: { boxShadow: "0px 2px 6px rgba(15,42,29,0.12)" as any },
    }),
  },

  // Services filter row
  filterRow: { flexDirection: "row", gap: 8, marginBottom: 12 },
  searchBox: { flex: 1, flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 10, height: 38 },
  searchInput: { flex: 1, fontSize: 13, color: colors.textMain, paddingVertical: 0 },

  // Service category grid
  categoryGridSection: { marginBottom: 14 },
  sectionHeaderRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 10 },
  sectionTitle: { fontSize: 13, fontWeight: "800", letterSpacing: 0.3, color: colors.textMain, textTransform: "uppercase" },
  clearLink: { fontSize: 12, fontWeight: "700", color: colors.primary },
  categoryGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  catTile: {
    width: "31.5%",
    aspectRatio: 1,
    backgroundColor: colors.surface,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 6,
    paddingVertical: 10,
    position: "relative",
  },
  catIconWrap: {
    width: 44, height: 44, borderRadius: 12,
    alignItems: "center", justifyContent: "center", marginBottom: 6,
  },
  catTileText: {
    fontSize: 11, fontWeight: "700", color: colors.textMain,
    textAlign: "center", lineHeight: 14,
  },
  catCountPill: {
    position: "absolute", top: 6, right: 6,
    minWidth: 20, height: 20, borderRadius: 10,
    paddingHorizontal: 6, alignItems: "center", justifyContent: "center",
  },
  catCountText: { color: "#fff", fontSize: 10, fontWeight: "800" },

  // Subcategory chip strip
  subChip: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 12, paddingVertical: 7,
    borderRadius: 999,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  subChipOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  subChipText: { fontSize: 12, fontWeight: "700", color: colors.textMain },

  // Location button + LIVE badge
  locBtn: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 10, paddingHorizontal: 12,
    borderRadius: 12,
    backgroundColor: colors.primary + "15",
    borderWidth: 1, borderColor: colors.primary + "44",
    marginBottom: 12,
    minHeight: 52,
  },
  locBtnActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  locBtnText: { fontSize: 13, fontWeight: "800", color: colors.primary },
  locBtnHint: { fontSize: 10.5, color: colors.textMuted, marginTop: 1 },
  locBtnTextActive: { color: colors.primaryFg },
  activeDot: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "#ECFDF5",
    paddingHorizontal: 6, paddingVertical: 2,
    borderRadius: 4,
    borderWidth: 1, borderColor: "#A7F3D0",
  },
  activeDotInner: { width: 6, height: 6, borderRadius: 3, backgroundColor: "#10B981" },
  activeDotText: { fontSize: 9, fontWeight: "800", color: "#047857", letterSpacing: 0.4 },
  activeAgo: { fontSize: 10, color: colors.textMuted, marginTop: 2 },

  serviceCard: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, marginBottom: 10 },
  serviceAvatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  serviceAvatarText: { fontSize: 16, fontWeight: "800", color: colors.primary },
  serviceName: { fontSize: 14, fontWeight: "700", color: colors.textMain },
  serviceTitle: { fontSize: 12, color: colors.textMuted, marginTop: 1 },
  tag: { flexDirection: "row", alignItems: "center", paddingVertical: 2, paddingHorizontal: 8, backgroundColor: colors.surfaceMuted, borderRadius: 999 },
  tagText: { fontSize: 10, fontWeight: "600", color: colors.textMuted },
  servicePrice: { fontSize: 15, fontWeight: "800", color: colors.primary },

  emptyCard: { padding: 30, alignItems: "center", gap: 8 },
  emptyText: { fontSize: 14, fontWeight: "700", color: colors.textMain, marginTop: 8 },
  emptySubtext: { fontSize: 12, color: colors.textMuted, textAlign: "center" },

  modalBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 22, paddingBottom: Platform.OS === "ios" ? 36 : 22 },
  modalHandle: { width: 40, height: 4, borderRadius: 2, backgroundColor: colors.border, alignSelf: "center", marginBottom: 14 },
  modalTitle: { fontSize: 20, fontWeight: "800", color: colors.textMain },
  modalSubtitle: { fontSize: 13, color: colors.textMuted, marginTop: 2, marginBottom: 8 },
  modalDesc: { fontSize: 13, color: colors.textMain, marginBottom: 12, lineHeight: 18 },
  modalRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 6 },
  modalRowText: { fontSize: 13, color: colors.textMain },
  modalBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 12, borderRadius: 12 },
  modalBtnPrimary: { backgroundColor: colors.primary },
  modalBtnGhost: { backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border },
  modalBtnText: { fontSize: 14, fontWeight: "800" },
});

// Silence unused-warning: `radii` is imported for downstream re-exports.
void radii;
