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
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";

type Product = { id: string; name: string; price: number; image_url: string; description?: string };
type ServiceProvider = {
  id: string;
  name: string;
  phone?: string;
  email: string;
  referral_code: string;
  service_name: string;
  service_category: string;
  service_pincode: string;
  service_charge: number;
  service_description?: string;
};
type Mode = "shop" | "services";

export default function ShopScreen() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("shop");

  // ---- Shop state ----
  const [items, setItems] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [cartCount, setCartCount] = useState(0);

  // ---- Services state ----
  const [services, setServices] = useState<ServiceProvider[]>([]);
  const [servicesLoading, setServicesLoading] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [pincodeQ, setPincodeQ] = useState("");
  const [categoryQ, setCategoryQ] = useState("all");
  const [categories, setCategories] = useState<string[]>([]);
  const [myStatus, setMyStatus] = useState<string | null>(null);
  const [contactOf, setContactOf] = useState<ServiceProvider | null>(null);
  const [bookingId, setBookingId] = useState<string | null>(null);

  const loadShop = useCallback(async () => {
    try {
      const { data } = await api.get<{ items: Product[] }>("/products");
      setItems(data.items || []);
      const cart = await api.get<{ items: any[] }>("/cart");
      setCartCount((cart.data.items || []).reduce((s, i: any) => s + (i.quantity || 0), 0));
    } catch (e) {
      console.warn(e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const loadServices = useCallback(async () => {
    setServicesLoading(true);
    try {
      const params: Record<string, string> = {};
      if (searchQ) params.q = searchQ;
      if (pincodeQ) params.pincode = pincodeQ;
      if (categoryQ && categoryQ !== "all") params.category = categoryQ;
      const { data } = await api.get<{ items: ServiceProvider[] }>("/services", { params });
      setServices(data.items || []);
      const cats = await api.get<{ categories: string[] }>("/services/categories");
      setCategories(cats.data.categories || []);
      const mine = await api.get<{ service_status: string | null }>("/service/me");
      setMyStatus(mine.data.service_status || null);
    } catch (e) {
      console.warn(e);
    } finally {
      setServicesLoading(false);
    }
  }, [searchQ, pincodeQ, categoryQ]);

  useFocusEffect(useCallback(() => {
    if (mode === "shop") loadShop();
    else loadServices();
  }, [mode, loadShop, loadServices]));

  useEffect(() => {
    if (mode === "services") {
      const t = setTimeout(loadServices, 300);
      return () => clearTimeout(t);
    }
  }, [searchQ, pincodeQ, categoryQ, mode, loadServices]);

  const addToCart = async (p: Product) => {
    setAdding(p.id);
    try {
      await api.post("/cart/add", { product_id: p.id, quantity: 1 });
      setCartCount((c) => c + 1);
    } catch (e) {
      Alert.alert("Could not add", formatApiError(e));
    } finally {
      setAdding(null);
    }
  };

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

  if (loading && mode === "shop") {
    return <SafeAreaView style={styles.safe}><View style={styles.center}><ActivityIndicator color={colors.primary} /></View></SafeAreaView>;
  }

  // ============ Render ============
  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView
        contentContainerStyle={styles.container}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => { setRefreshing(true); mode === "shop" ? loadShop() : loadServices(); }}
          />
        }
        keyboardShouldPersistTaps="handled"
      >
        {/* Hero header */}
        <GradientCard variant={mode === "shop" ? "sunset" : "royal"} style={{ marginBottom: 12, padding: 22 }}>
          <View style={{ flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between" }}>
            <View style={{ flex: 1 }}>
              <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.85)", fontWeight: "700" }}>
                {mode === "shop" ? "SHOP" : "SERVICES"}
              </Text>
              <Text style={{ fontSize: 26, fontWeight: "800", color: "#fff", letterSpacing: -1, marginTop: 6 }}>
                {mode === "shop" ? "Member store" : "Find local talent"}
              </Text>
              <Text style={{ fontSize: 13, color: "rgba(255,255,255,0.9)", marginTop: 6 }}>
                {mode === "shop" ? "Pay using your wallet earnings." : "Book a verified provider in your pincode."}
              </Text>
            </View>
            {mode === "shop" && (
              <TouchableOpacity onPress={() => router.push("/cart")} style={[styles.cartBtn, { backgroundColor: "rgba(255,255,255,0.2)", borderWidth: 0 }]} testID="shop-cart-btn">
                <Feather name="shopping-cart" size={18} color="#fff" />
                {cartCount > 0 && (
                  <View style={[styles.cartBadge, { backgroundColor: "#fff" }]}>
                    <Text style={[styles.cartBadgeText, { color: "#E57A44" }]}>{cartCount > 9 ? "9+" : cartCount}</Text>
                  </View>
                )}
              </TouchableOpacity>
            )}
          </View>
        </GradientCard>

        {/* Mode toggle */}
        <View style={styles.pillRow}>
          <TouchableOpacity
            style={[styles.pill, mode === "shop" && styles.pillActive]}
            onPress={() => setMode("shop")}
          >
            <Feather name="shopping-bag" size={14} color={mode === "shop" ? colors.primaryFg : colors.textMain} />
            <Text style={[styles.pillText, mode === "shop" && styles.pillTextActive]}>Shop</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.pill, mode === "services" && styles.pillActive]}
            onPress={() => setMode("services")}
          >
            <Feather name="briefcase" size={14} color={mode === "services" ? colors.primaryFg : colors.textMain} />
            <Text style={[styles.pillText, mode === "services" && styles.pillTextActive]}>Services</Text>
          </TouchableOpacity>
        </View>

        {/* === SHOP === */}
        {mode === "shop" && (
          <>
            <View style={styles.grid}>
              {items.map((p) => (
                <View key={p.id} style={styles.card} testID={`product-${p.id}`}>
                  <Image source={{ uri: p.image_url }} style={styles.image} />
                  <Text style={styles.name} numberOfLines={2}>{p.name}</Text>
                  <View style={styles.cardFooter}>
                    <Text style={styles.price}>{formatINR(p.price)}</Text>
                    <TouchableOpacity
                      style={[styles.addBtn, adding === p.id && { opacity: 0.5 }]}
                      onPress={() => addToCart(p)}
                      disabled={adding === p.id}
                    >
                      {adding === p.id ? <ActivityIndicator color={colors.primaryFg} size="small" /> : <Feather name="plus" size={16} color={colors.primaryFg} />}
                    </TouchableOpacity>
                  </View>
                </View>
              ))}
            </View>
            {cartCount > 0 && (
              <TouchableOpacity onPress={() => router.push("/cart")} style={styles.checkoutBar}>
                <Feather name="shopping-cart" size={18} color={colors.accentFg} />
                <Text style={styles.checkoutBarText}>{cartCount} item{cartCount > 1 ? "s" : ""} in cart</Text>
                <Feather name="arrow-right" size={18} color={colors.accentFg} />
              </TouchableOpacity>
            )}
          </>
        )}

        {/* === SERVICES === */}
        {mode === "services" && (
          <>
            {/* Apply CTA */}
            <TouchableOpacity
              style={styles.applyCard}
              onPress={() => router.push("/services/apply" as any)}
            >
              <Feather name={myStatus === "approved" ? "check-circle" : "user-plus"} size={20} color={colors.primaryFg} />
              <View style={{ flex: 1 }}>
                <Text style={{ color: "#fff", fontWeight: "800", fontSize: 14 }}>
                  {myStatus === "approved" ? "You're a service provider" : myStatus === "pending" ? "Application under review" : myStatus === "rejected" ? "Apply again" : "Earn — list your service"}
                </Text>
                <Text style={{ color: "rgba(255,255,255,0.85)", fontSize: 12, marginTop: 2 }}>
                  {myStatus === "approved" ? "Tap to update or view bookings" : myStatus === "pending" ? "Awaiting admin approval" : "Pincode, charge, category"}
                </Text>
              </View>
              <Feather name="chevron-right" size={20} color="#fff" />
            </TouchableOpacity>

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
              <View style={[styles.searchBox, { width: 110 }]}>
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

            {categories.length > 0 && (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 14 }} contentContainerStyle={{ gap: 8 }}>
                <TouchableOpacity style={[styles.chip, categoryQ === "all" && styles.chipActive]} onPress={() => setCategoryQ("all")}>
                  <Text style={[styles.chipText, categoryQ === "all" && styles.chipTextActive]}>All</Text>
                </TouchableOpacity>
                {categories.map((c) => (
                  <TouchableOpacity key={c} style={[styles.chip, categoryQ === c && styles.chipActive]} onPress={() => setCategoryQ(c)}>
                    <Text style={[styles.chipText, categoryQ === c && styles.chipTextActive]}>{c}</Text>
                  </TouchableOpacity>
                ))}
              </ScrollView>
            )}

            {/* List */}
            {servicesLoading && services.length === 0 ? (
              <View style={[styles.center, { paddingVertical: 40 }]}>
                <ActivityIndicator color={colors.primary} />
              </View>
            ) : services.length === 0 ? (
              <View style={styles.emptyCard}>
                <Feather name="briefcase" size={28} color={colors.textMuted} />
                <Text style={styles.emptyText}>No service providers found.</Text>
                <Text style={styles.emptySubtext}>Try a different pincode or category — or be the first to list yours!</Text>
              </View>
            ) : (
              services.map((s) => (
                <TouchableOpacity key={s.id} style={styles.serviceCard} onPress={() => setContactOf(s)}>
                  <View style={styles.serviceAvatar}>
                    <Text style={styles.serviceAvatarText}>{(s.name || "?")[0].toUpperCase()}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.serviceName} numberOfLines={1}>{s.name}</Text>
                    <Text style={styles.serviceTitle} numberOfLines={1}>{s.service_name}</Text>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 10, marginTop: 4 }}>
                      <View style={styles.tag}><Text style={styles.tagText}>{s.service_category}</Text></View>
                      <View style={styles.tag}><Feather name="map-pin" size={10} color={colors.textMuted} /><Text style={styles.tagText}> {s.service_pincode}</Text></View>
                    </View>
                  </View>
                  <View style={{ alignItems: "flex-end" }}>
                    <Text style={styles.servicePrice}>{formatINR(s.service_charge || 0)}</Text>
                    <Feather name="chevron-right" size={18} color={colors.textMuted} />
                  </View>
                </TouchableOpacity>
              ))
            )}
          </>
        )}
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
                  <Feather name="dollar-sign" size={14} color={colors.textMuted} />
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
  container: { padding: spacing.screen, paddingBottom: 60 },
  pillRow: { flexDirection: "row", gap: 8, marginBottom: 14 },
  pill: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 10, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  pillActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  pillText: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  pillTextActive: { color: colors.primaryFg },

  cartBtn: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  cartBadge: { position: "absolute", top: -2, right: -2, minWidth: 20, height: 20, borderRadius: 10, alignItems: "center", justifyContent: "center", paddingHorizontal: 5 },
  cartBadgeText: { fontSize: 10, fontWeight: "800" },

  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  card: { flexBasis: "48%", flexGrow: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 18, overflow: "hidden", padding: 10 },
  image: { width: "100%", height: 130, borderRadius: 12, backgroundColor: colors.surfaceMuted },
  name: { fontSize: 13, fontWeight: "700", color: colors.textMain, marginTop: 10, minHeight: 34 },
  cardFooter: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 8 },
  price: { fontSize: 15, fontWeight: "800", color: colors.primary },
  addBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  checkoutBar: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 10, backgroundColor: colors.accent, paddingVertical: 14, borderRadius: radii.button, marginTop: 24 },
  checkoutBarText: { color: colors.accentFg, fontWeight: "700", fontSize: 15, flex: 1, textAlign: "center" },

  applyCard: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14, borderRadius: 14, backgroundColor: colors.primary, marginBottom: 14 },
  filterRow: { flexDirection: "row", gap: 8, marginBottom: 12 },
  searchBox: { flex: 1, flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 10, paddingHorizontal: 10, height: 38 },
  searchInput: { flex: 1, fontSize: 13, color: colors.textMain, paddingVertical: 0 },
  chip: { paddingVertical: 6, paddingHorizontal: 12, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 12, fontWeight: "600", color: colors.textMain },
  chipTextActive: { color: colors.primaryFg },

  serviceCard: { flexDirection: "row", alignItems: "center", gap: 12, padding: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: 14, marginBottom: 10 },
  serviceAvatar: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.brand100, alignItems: "center", justifyContent: "center" },
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
