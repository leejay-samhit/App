import { useCallback, useRef, useState } from "react";
import { View, Text, StyleSheet, ScrollView, FlatList, Modal, TextInput, TouchableOpacity, ActivityIndicator, Alert, RefreshControl, Image, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import { api, formatApiError, resolveImageUrl } from "../../src/api";
import { colors, radii, spacing, formatINR } from "../../src/theme";
import { GradientCard } from "../../src/gradient-card";
import { RichProductEditor } from "../../src/rich-product-editor";
import { FadeSlideIn, StatCardSkeleton, ListRowSkeleton } from "../../src/anim";
import { useSwipePager } from "../../src/use-swipe-pager";
import { ProductImage } from "../../src/product-image";

/** Products fetched per page by the vendor dashboard list. */
const PRODUCT_PAGE = 250;   // Nov 2026 — owner asked for 250 per page

type Stats = {
  total_sales: number; total_earnings: number; today_earnings: number;
  today_orders: number; all_orders: number; products_count: number;
  published_count: number; wallet_balance: number;
  // Jul 2026 — Per-channel breakdown for the earnings drill-down.
  online_total?: number; online_today?: number; online_orders_all?: number; online_orders_today?: number;
  pos_total?: number; pos_today?: number; pos_orders_all?: number; pos_orders_today?: number;
  // Jun 2026 — Daily cash reconciliation figures.
  cod_pending_total?: number; cod_pending_count?: number;
  cod_collected_today?: number; cod_collected_today_count?: number;
};
type EarningRow = {
  channel: "online" | "pos";
  id: string;
  order_id?: string;
  invoice_no?: string;
  created_at: string;
  product_name: string;
  qty: number;
  line_total: number;
  buyer_email?: string;
  customer_name?: string;
};
type Product = { id: string; name: string; price: number; stock: number; image_url: string; description?: string; category?: string; is_published?: boolean; review_status?: string; created_at?: string; interested_count?: number };
type Sale = { id: string; order_id: string; product_id: string; product_name: string; qty: number; line_total: number; vendor_share: number; commission_pct: number; created_at: string };
type InterestedUser = { id: string; name: string; email: string; phone?: string };
type QuestionAnswer = { id: string; by_id: string; by_name: string; by_role: string; text: string; created_at: string };
type VendorQuestion = {
  id: string; product_id: string; product_name: string; product_image: string;
  asker_id: string; asker_name: string; text: string;
  answers: QuestionAnswer[]; answered: boolean; created_at: string;
};

// Tab order — also the sequence the left/right swipe walks through.
const VENDOR_TABS: ("home" | "products" | "sales" | "qa")[] = ["home", "products", "sales", "qa"];

export default function VendorDashboard() {
  const router = useRouter();
  const [tab, setTab] = useState<"home" | "products" | "sales" | "qa">("home");
  // Jun 2026 — Same left/right swipe behaviour as the rest of the app.
  const stepTab = useCallback((dir: 1 | -1) => {
    const next = VENDOR_TABS.indexOf(tab) + dir;
    if (next < 0 || next >= VENDOR_TABS.length) return;
    setTab(VENDOR_TABS[next]);
  }, [tab]);
  const swipeHandlers = useSwipePager({
    onNext: () => stepTab(1),
    onPrev: () => stepTab(-1),
  });
  const [stats, setStats] = useState<Stats | null>(null);
  const [products, setProducts] = useState<Product[]>([]);
  const [sales, setSales] = useState<Sale[]>([]);
  const [questions, setQuestions] = useState<VendorQuestion[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  // Jul 2026 — Earnings drill-down modal state
  const [earningsOpen, setEarningsOpen] = useState<null | { scope: "today" | "lifetime" }>(null);
  const [earningRows, setEarningRows] = useState<EarningRow[]>([]);
  const [earningsLoading, setEarningsLoading] = useState(false);
  const [earningsMonth, setEarningsMonth] = useState<string>(""); // YYYY-MM
  const [earningsChannel, setEarningsChannel] = useState<"" | "online" | "pos">("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [interestedFor, setInterestedFor] = useState<Product | null>(null);
  const [interestedUsers, setInterestedUsers] = useState<InterestedUser[]>([]);
  const [interestedLoading, setInterestedLoading] = useState(false);
  const [answeringQid, setAnsweringQid] = useState<string | null>(null);
  const [answerText, setAnswerText] = useState("");
  const [submittingAnswer, setSubmittingAnswer] = useState(false);
  // Jun 2026 — paged product list (see /vendor/me/products).
  const [productTotal, setProductTotal] = useState(0);
  // Nov 2026 — numbered pages of 250 instead of "Load more", which restarted
  // from the first page on every refocus and so never reached a big catalogue.
  const [productPage, setProductPage] = useState(0);
  const productPageRef = useRef(0);
  // How many of the page's 250 cards are mounted (grows as you scroll).
  const [visibleCount, setVisibleCount] = useState(40);

  const load = useCallback(async () => {
    const pageNo = productPageRef.current;
    try {
      const [s, p, sl, qa] = await Promise.all([
        api.get<Stats>("/vendor/me/stats"),
        api.get<any>("/vendor/me/products", { params: { limit: PRODUCT_PAGE, offset: pageNo * PRODUCT_PAGE } }),
        api.get<{ items: Sale[] }>("/vendor/me/sales"),
        api.get<{ items: VendorQuestion[]; pending_count: number }>("/vendor/me/questions").catch(() => ({ data: { items: [], pending_count: 0 } as any })),
      ]);
      // Jun 2026 — /vendor/me/products is now PAGED ({items,total,has_more}).
      // The old hard cap silently dropped everything past the first 1,000
      // rows, so a restored catalogue looked incomplete. Legacy array shape
      // is still accepted for older builds.
      const prodData = p.data;
      const prodList: Product[] = Array.isArray(prodData) ? prodData : (prodData?.items || []);
      // Nov 2026 — "interested" counts live on the public list. Ask for THIS
      // page's ids: the old call fetched the public FIRST page, so every
      // badge past product 60 showed 0.
      const cMap = new Map<string, number>();
      if (prodList.length) {
        try {
          const pubResp = await api.get<any>("/products", {
            params: { ids: prodList.map((x) => x.id).join(",") },
          });
          const pubList: any[] = Array.isArray(pubResp.data) ? pubResp.data : (pubResp.data?.items || []);
          pubList.forEach((x: any) => cMap.set(x.id, x.interested_count || 0));
        } catch { /* badge is cosmetic */ }
      }
      setStats(s.data);
      setProducts(prodList.map((it) => ({ ...it, interested_count: cMap.get(it.id) || 0 })));
      const tot = Number(Array.isArray(prodData) ? prodList.length : (prodData?.total ?? prodList.length));
      setProductTotal(tot);
      // Deleting the last product on the final page would strand the vendor on
      // an empty page — step back to the last page that still has rows.
      if (prodList.length === 0 && tot > 0 && pageNo > 0) {
        const last = Math.max(0, Math.ceil(tot / PRODUCT_PAGE) - 1);
        if (last !== pageNo) {
          productPageRef.current = last;
          setProductPage(last);
          const back = await api.get<any>("/vendor/me/products", { params: { limit: PRODUCT_PAGE, offset: last * PRODUCT_PAGE } });
          const backList: Product[] = Array.isArray(back.data) ? back.data : (back.data?.items || []);
          setProducts(backList.map((it) => ({ ...it, interested_count: cMap.get(it.id) || 0 })));
        }
      }
      setSales(sl.data.items || []);
      setQuestions(qa.data?.items || []);
      setPendingCount(qa.data?.pending_count || 0);
    } catch (e) {
      // If 403 (not approved), redirect to apply
      const msg = formatApiError(e);
      if (String(msg).toLowerCase().includes("vendor")) router.replace("/vendor/apply" as any);
      else Alert.alert("Error", msg);
    }
    finally { setLoading(false); setRefreshing(false); }
  }, [router]);

  const goToProductPage = useCallback((n: number) => {
    productPageRef.current = n;
    setProductPage(n);
    setVisibleCount(40);   // a new page starts from the top
    setLoading(true);
    load();
  }, [load]);

  useFocusEffect(useCallback(() => { setLoading(true); load(); }, [load]));

  const onAddProduct = () => { setEditing({ id: "", name: "", price: 0, stock: 100, image_url: "", description: "", category: "", is_published: true }); setEditorOpen(true); };
  const onEditProduct = async (p: Product) => {
    // Jun 2026 — the product LIST is now slim (no base64 cover, no gallery)
    // so the dashboard loads fast. Pull the full document before opening the
    // editor, otherwise the vendor would see an empty cover / gallery and
    // wipe their photos on save.
    setEditing({ ...p });
    setEditorOpen(true);
    try {
      const r = await api.get<any>(`/vendor/me/products/${p.id}`);
      if (r.data?.id) setEditing(r.data);
    } catch { /* keep the slim row — cover shows as the thumbnail URL */ }
  };

  const onDeleteProduct = (p: Product) => {
    Alert.alert("Delete product?", `\"${p.name}\" will be removed permanently.`, [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: async () => {
        try { await api.delete(`/vendor/me/products/${p.id}`); await load(); }
        catch (e) { Alert.alert("Couldn't delete", formatApiError(e)); }
      }}
    ]);
  };

  const onSubmitAnswer = async (q: VendorQuestion) => {
    const t = answerText.trim();
    if (!t) return;
    setSubmittingAnswer(true);
    try {
      await api.post(`/products/${q.product_id}/questions/${q.id}/answer`, { text: t });
      setAnswerText("");
      setAnsweringQid(null);
      await load();
    } catch (e) {
      Alert.alert("Couldn't post answer", formatApiError(e));
    } finally { setSubmittingAnswer(false); }
  };

  // Jul 2026 — Earnings drill-down: fetch the raw per-row list for the
  // scope (today / lifetime) and optional month + channel filters.
  const fetchEarnings = useCallback(async (scope: "today" | "lifetime", month: string, channel: "" | "online" | "pos") => {
    setEarningsLoading(true);
    try {
      const params: Record<string, string> = {};
      if (scope === "today") {
        const today = new Date().toISOString().slice(0, 10);
        params.from_date = today;
        // Backend uses `to_date` as EXCLUSIVE upper bound so bump by 1 day.
        const t = new Date(); t.setDate(t.getDate() + 1);
        params.to_date = t.toISOString().slice(0, 10);
      } else if (month) {
        params.month = month;
      }
      if (channel) params.channel = channel;
      const r = await api.get<{ items: EarningRow[] }>("/vendor/me/earnings", { params });
      setEarningRows(r.data.items || []);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.warn("earnings fetch failed", formatApiError(e));
      setEarningRows([]);
    } finally { setEarningsLoading(false); }
  }, []);

  const openEarnings = useCallback((scope: "today" | "lifetime") => {
    setEarningsOpen({ scope });
    setEarningsMonth("");
    setEarningsChannel("");
    fetchEarnings(scope, "", "");
  }, [fetchEarnings]);

  if (loading) return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn}>
          <Feather name="arrow-left" size={20} color={colors.textMain} />
        </TouchableOpacity>
        <Text style={styles.title}>Vendor Dashboard</Text>
      </View>
      <View style={{ paddingHorizontal: spacing.screen, paddingTop: 10 }}>
        <View style={styles.statsGrid}>
          {[...Array(6)].map((_, i) => <StatCardSkeleton key={i} />)}
        </View>
      </View>
    </SafeAreaView>
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.iconBtn} testID="vendor-back"><Feather name="arrow-left" size={20} color={colors.textMain} /></TouchableOpacity>
        <Text style={styles.title}>Vendor Panel</Text>
        <TouchableOpacity onPress={onAddProduct} style={styles.iconBtn} testID="vendor-add"><Feather name="plus" size={22} color={colors.primary} /></TouchableOpacity>
      </View>

      <View style={styles.tabsRow}>
        {[
          { k: "home", l: "Overview", icon: "home" as const },
          { k: "products", l: "Products", icon: "package" as const },
          { k: "sales", l: "Sales", icon: "trending-up" as const },
          { k: "qa", l: "Q&A", icon: "message-circle" as const, badge: pendingCount },
        ].map((t) => (
          <TouchableOpacity key={t.k} onPress={() => setTab(t.k as any)} style={[styles.tab, tab === t.k && styles.tabActive]} testID={`vendor-tab-${t.k}`}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <Text style={[styles.tabText, tab === t.k && { color: colors.primary }]}>{t.l}</Text>
              {t.badge && t.badge > 0 ? (
                <View style={styles.tabBadge}><Text style={styles.tabBadgeText}>{t.badge}</Text></View>
              ) : null}
            </View>
          </TouchableOpacity>
        ))}
      </View>

      {/* Jun 2026 — Swipe surface: a left/right flick moves through the
          Overview · Products · Sales · Q&A tabs, matching the app-wide
          gesture. */}
      <View style={{ flex: 1 }} {...swipeHandlers}>
      {tab === "home" && stats && (
        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}>
          <FadeSlideIn triggerKey={`home-${refreshing ? "r" : "d"}`}>
          <GradientCard variant="emerald" style={{ marginBottom: 14, padding: 18 }}>
            <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.85)", fontWeight: "700" }}>VENDOR</Text>
            <Text style={{ fontSize: 24, fontWeight: "900", color: "#fff", marginTop: 4, letterSpacing: -0.6 }}>
              {formatINR(stats.today_earnings)} today
            </Text>
            <Text style={{ fontSize: 12, color: "rgba(255,255,255,0.9)", marginTop: 4 }}>
              {stats.today_orders} order{stats.today_orders === 1 ? "" : "s"} · {stats.published_count} of {stats.products_count} products live
            </Text>
          </GradientCard>

          {/* Cloud POS quick-links — mirrors the full /vendor/* module on the web. */}
          <View style={{ marginBottom: 14 }}>
            <Text style={{ fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 1.2, textTransform: "uppercase", marginBottom: 8 }}>Cloud POS</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
              {[
                { key: "orders", label: "Shop orders", icon: "package", path: "/vendor/orders", primary: true },
                { key: "returns", label: "Returns", icon: "rotate-ccw", path: "/vendor/returns" },
                { key: "networth", label: "Net worth", icon: "trending-up", path: "/vendor/net-worth" },
                { key: "pos", label: "New sale", icon: "shopping-cart", path: "/vendor/pos" },
                // Sep 2026 — "Store sale" history tile removed on the owner's
                // request: it listed every order with ₹0 amounts and simply
                // duplicated "All invoices", which shows both shop orders and
                // store sales with the correct totals.
                { key: "invoices", label: "All invoices", icon: "file-text", path: "/vendor/invoices" },
                { key: "cash", label: "Cash", icon: "dollar-sign", path: "/vendor/cash" },
                { key: "analytics", label: "Analytics", icon: "bar-chart-2", path: "/vendor/analytics" },
                { key: "settings", label: "POS settings", icon: "settings", path: "/vendor/settings" },
              ].map(t => (
                <TouchableOpacity key={t.key} onPress={() => router.push(t.path as any)}
                  style={{
                    width: "31%", padding: 12, borderRadius: 12,
                    backgroundColor: t.primary ? colors.primary : colors.surface,
                    borderWidth: t.primary ? 0 : 1, borderColor: colors.border,
                    alignItems: "center",
                  }}
                  activeOpacity={0.85}
                  testID={`vendor-pos-link-${t.key}`}
                >
                  <Feather name={t.icon as any} size={20} color={t.primary ? "#fff" : colors.primary} />
                  <Text style={{ marginTop: 6, fontSize: 12, fontWeight: "700", color: t.primary ? "#fff" : colors.textMain }}>{t.label}</Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>

          {/* ── Nov 2026 — Profile & delivery-zone shortcut ──
              Approved vendors couldn't easily discover the "Request
              Edit" flow because tapping "Vendor Panel" on the profile
              tab routes here directly.  This banner exposes the
              delivery-radius / pincode-tag update path prominently. */}
          <TouchableOpacity
            onPress={() => router.push("/vendor/request-edit" as any)}
            activeOpacity={0.85}
            style={{
              flexDirection: "row", alignItems: "center", gap: 12,
              padding: 14, marginBottom: 14,
              borderRadius: 16, borderWidth: 1, borderColor: colors.primary,
              backgroundColor: colors.brand100,
            }}
            testID="vendor-request-edit-cta"
          >
            <View style={{
              width: 44, height: 44, borderRadius: 22,
              backgroundColor: "#fff",
              alignItems: "center", justifyContent: "center",
              borderWidth: 2, borderColor: colors.primary,
            }}>
              <Feather name="map-pin" size={20} color={colors.primary} />
            </View>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={{ fontSize: 14, fontWeight: "800", color: colors.textMain }}>
                Update delivery zone & profile
              </Text>
              <Text style={{ fontSize: 11, color: colors.textMuted, marginTop: 3, lineHeight: 15 }} numberOfLines={2}>
                Change km-radius, add extra pincodes, or update shop details.  Admin reviews every change.
              </Text>
            </View>
            <Feather name="chevron-right" size={18} color={colors.primary} />
          </TouchableOpacity>
          <FadeSlideIn>
          <View style={styles.statsGrid}>
            {/* Jun 2026 — Even 2-column grid: every cell is the same
                flex-basis + min-height so the boxes align perfectly.
                Earnings + order cells are tappable drill-downs. */}
            <TouchableOpacity activeOpacity={0.8} style={styles.statCell} onPress={() => openEarnings("today")} testID="stat-today-earn">
              <StatCard icon="trending-up" label="TODAY EARNINGS" value={formatINR(stats.today_earnings)} color="#1F6B44" />
            </TouchableOpacity>
            <TouchableOpacity activeOpacity={0.8} style={styles.statCell} onPress={() => router.push("/vendor/orders" as any)} testID="stat-today-orders">
              <StatCard icon="package" label="TODAY ORDERS" value={String(stats.today_orders)} color="#1F5E9E" />
            </TouchableOpacity>
            <TouchableOpacity activeOpacity={0.8} style={styles.statCell} onPress={() => openEarnings("lifetime")} testID="stat-life-earn">
              <StatCard icon="tag" label="LIFETIME EARNINGS" value={formatINR(stats.total_earnings)} color={colors.primary} />
            </TouchableOpacity>
            <View style={styles.statCell}>
              <StatCard icon="shopping-cart" label="LIFETIME SALES" value={formatINR(stats.total_sales)} color="#7A4A0E" />
            </View>
            <View style={styles.statCell}>
              <StatCard icon="box" label="PRODUCTS" value={`${stats.published_count}/${stats.products_count}`} color="#1F5E9E" />
            </View>
            <TouchableOpacity
              activeOpacity={0.8}
              style={styles.statCell}
              onPress={() => router.push("/(tabs)/wallet" as any)}
              testID="stat-wallet"
            >
              <StatCard icon="credit-card" label="WALLET" value={formatINR(stats.wallet_balance)} color="#1F6B44" />
            </TouchableOpacity>
          </View>
          </FadeSlideIn>
          {/* Per-channel breakdown pill (Shop orders + Store sale) */}
          <FadeSlideIn delay={60}>
          <View style={styles.channelRow}>
            <View style={styles.channelPill}>
              <Feather name="globe" size={12} color="#1D4ED8" />
              <View style={{ flex: 1 }}>
                <Text style={styles.channelPillLabel}>SHOP ORDERS</Text>
                <Text style={styles.channelPillValue}>{formatINR(stats.online_total || 0)}</Text>
                <Text style={styles.channelPillMeta}>{stats.online_orders_all || 0} order{(stats.online_orders_all || 0) === 1 ? "" : "s"}</Text>
              </View>
            </View>
            <View style={[styles.channelPill, { backgroundColor: "#ECFDF5", borderColor: "#A7F3D0" }]}>
              <Feather name="printer" size={12} color="#047857" />
              <View style={{ flex: 1 }}>
                <Text style={[styles.channelPillLabel, { color: "#047857" }]}>STORE SALE</Text>
                <Text style={styles.channelPillValue}>{formatINR(stats.pos_total || 0)}</Text>
                <Text style={styles.channelPillMeta}>{stats.pos_orders_all || 0} invoice{(stats.pos_orders_all || 0) === 1 ? "" : "s"}</Text>
              </View>
            </View>
          </View>
          </FadeSlideIn>
          {/* Jun 2026 — DELIVERY CASH SUMMARY.  Vendors reconcile their
              drawer at closing time, so we surface both the cash already
              taken in today and what's still out with riders. */}
          <FadeSlideIn delay={90}>
          <TouchableOpacity
            activeOpacity={0.85}
            onPress={() => router.push("/vendor/orders" as any)}
            style={styles.cashCard}
            testID="cash-summary-card"
          >
            <View style={styles.cashHeader}>
              <Feather name="dollar-sign" size={14} color="#92400E" />
              <Text style={styles.cashTitle}>CASH TO COLLECT</Text>
              <Feather name="chevron-right" size={16} color="#92400E" />
            </View>
            <View style={styles.cashRow}>
              <View style={styles.cashCell}>
                <Text style={styles.cashLabel}>COLLECTED TODAY</Text>
                <Text style={styles.cashValueDone} testID="cash-collected-today">
                  {formatINR(stats.cod_collected_today || 0)}
                </Text>
                <Text style={styles.cashMeta}>
                  {stats.cod_collected_today_count || 0} delivered
                </Text>
              </View>
              <View style={styles.cashDivider} />
              <View style={[styles.cashCell, { alignItems: "flex-end" }]}>
                <Text style={styles.cashLabel}>STILL OUT WITH RIDERS</Text>
                <Text style={styles.cashValuePending} testID="cash-pending">
                  {formatINR(stats.cod_pending_total || 0)}
                </Text>
                <Text style={styles.cashMeta}>
                  {stats.cod_pending_count || 0} order{(stats.cod_pending_count || 0) === 1 ? "" : "s"}
                </Text>
              </View>
            </View>
            <Text style={styles.cashHint}>
              {(stats.cod_pending_total || 0) > 0
                ? `Collect ${formatINR(stats.cod_pending_total || 0)} more to close the day clean`
                : "All cash orders settled — nothing pending 🎉"}
            </Text>
          </TouchableOpacity>
          </FadeSlideIn>
          <FadeSlideIn delay={120}>
          <TouchableOpacity onPress={onAddProduct} style={styles.primaryBtn} testID="vendor-add-cta">
            <Feather name="plus-circle" size={18} color={colors.primaryFg} /><Text style={styles.primaryBtnText}>  Add new product</Text>
          </TouchableOpacity>
          </FadeSlideIn>
          </FadeSlideIn>
        </ScrollView>
      )}

      {tab === "products" && (
        products.length === 0 ? (
          <View style={styles.center}>
            <Feather name="package" size={48} color={colors.textMuted} />
            <Text style={styles.emptyTitle}>No products yet</Text>
            <TouchableOpacity onPress={onAddProduct} style={styles.primaryBtn} testID="vendor-add-empty">
              <Feather name="plus" size={16} color={colors.primaryFg} /><Text style={styles.primaryBtnText}>  Add product</Text>
            </TouchableOpacity>
            {/* Jun 2026 — a brand-new shop can start by restoring a catalogue
                backup taken from another login instead of typing it all in. */}
            <TouchableOpacity onPress={() => router.push("/vendor/catalogue-backup" as any)} style={styles.backupBtn} testID="vendor-backup-empty">
              <Feather name="upload-cloud" size={15} color={colors.primary} />
              <Text style={styles.backupBtnText}>Restore from a backup file</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <ScrollView
            contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }}
            // Nov 2026 — grow the rendered slice as the vendor scrolls. All
            // 250 cards used to mount at once, which stuttered on low-end
            // phones; now only what has been scrolled to is on screen.
            scrollEventThrottle={64}
            onScroll={(e) => {
              const { layoutMeasurement, contentOffset, contentSize } = e.nativeEvent;
              if (contentOffset.y + layoutMeasurement.height >= contentSize.height - layoutMeasurement.height) {
                setVisibleCount((n) => (n >= products.length ? n : n + 40));
              }
            }}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          >
            <TouchableOpacity onPress={() => router.push("/vendor/catalogue-backup" as any)} style={styles.backupRow} testID="vendor-backup-open">
              <Feather name="hard-drive" size={16} color={colors.primary} />
              <View style={{ flex: 1 }}>
                <Text style={styles.backupRowTitle}>Backup / restore catalogue</Text>
                <Text style={styles.backupRowHint}>Download all {productTotal || products.length} products, or restore them into another shop login</Text>
              </View>
              <Feather name="chevron-right" size={18} color={colors.textMuted} />
            </TouchableOpacity>
            <View style={styles.vendorGrid}>
              {products.slice(0, visibleCount).map((item) => {
                const oos = (item.stock || 0) === 0;
                const lowStock = (item.stock || 0) > 0 && (item.stock || 0) <= 5;
                return (
                  <TouchableOpacity
                    key={item.id}
                    activeOpacity={0.85}
                    onPress={() => onEditProduct(item)}
                    style={styles.vendorCard}
                    testID={`vendor-product-${item.id}`}
                  >
                    <View style={styles.vendorImgWrap}>
                      <ProductImage
                        uri={item.image_url}
                        name={item.name}
                        style={styles.vendorImg}
                        containerStyle={{ width: "100%", height: "100%" }}
                        resizeMode="cover"
                        testID={`vendor-product-${item.id}-img`}
                      />
                      {item.is_published === false && (
                        <View style={styles.vendorDraftPill}>
                          <Text style={styles.vendorDraftText}>
                            {item.review_status === "pending" ? "IN REVIEW" : "HIDDEN"}
                          </Text>
                        </View>
                      )}
                      {oos && (
                        <View style={styles.vendorOosOverlay} pointerEvents="none">
                          <Text style={styles.vendorOosText}>SOLD OUT</Text>
                        </View>
                      )}
                      {lowStock && !oos && (
                        <View style={styles.vendorLowStock}><Text style={styles.vendorLowStockText}>Only {item.stock}</Text></View>
                      )}
                      {(item.interested_count || 0) > 0 && (
                        <TouchableOpacity
                          style={styles.vendorInterestBadge}
                          onPress={async () => {
                            setInterestedFor(item);
                            setInterestedLoading(true);
                            try {
                              const r = await api.get<{ users: InterestedUser[] }>(`/products/${item.id}/interested`);
                              setInterestedUsers(r.data.users || []);
                            } catch (e) { Alert.alert("Couldn't load", formatApiError(e)); }
                            finally { setInterestedLoading(false); }
                          }}
                          testID={`vendor-interested-${item.id}`}
                        >
                          <Feather name="users" size={10} color="#fff" />
                          <Text style={styles.vendorInterestText}>{item.interested_count}</Text>
                        </TouchableOpacity>
                      )}
                    </View>
                    <View style={styles.vendorBody}>
                      {item.category ? <Text style={styles.vendorCat} numberOfLines={1}>{item.category}</Text> : null}
                      <Text style={styles.vendorName} numberOfLines={2}>{item.name}</Text>
                      <View style={styles.vendorFooterRow}>
                        <Text style={styles.vendorPrice}>{formatINR(item.price)}</Text>
                        <Text style={styles.vendorStockLabel}>Stock {item.stock ?? 0}</Text>
                      </View>
                      <View style={styles.vendorActions}>
                        <TouchableOpacity onPress={() => onEditProduct(item)} style={styles.vendorActionBtn} testID={`vendor-edit-${item.id}`}>
                          <Feather name="edit-2" size={13} color={colors.primary} />
                          <Text style={styles.vendorActionText}>Edit</Text>
                        </TouchableOpacity>
                        <TouchableOpacity onPress={() => onDeleteProduct(item)} style={[styles.vendorActionBtn, styles.vendorActionDanger]} testID={`vendor-del-${item.id}`}>
                          <Feather name="trash-2" size={13} color="#B3261E" />
                        </TouchableOpacity>
                      </View>
                    </View>
                  </TouchableOpacity>
                );
              })}
            </View>
            {/* Nov 2026 — numbered pages (250 per page). */}
            {productTotal > PRODUCT_PAGE ? (
              <View style={styles.vendorPager} testID="vendor-products-pager">
                <TouchableOpacity
                  onPress={() => goToProductPage(productPage - 1)}
                  disabled={productPage <= 0}
                  style={[styles.vendorPagerBtn, productPage <= 0 && { opacity: 0.35 }]}
                  testID="vendor-page-prev"
                >
                  <Feather name="chevron-left" size={18} color={colors.primary} />
                </TouchableOpacity>
                <ScrollView
                  horizontal
                  showsHorizontalScrollIndicator={false}
                  contentContainerStyle={{ gap: 6, paddingHorizontal: 6 }}
                  style={{ flex: 1 }}
                >
                  {Array.from({ length: Math.ceil(productTotal / PRODUCT_PAGE) }).map((_, i) => (
                    <TouchableOpacity
                      key={i}
                      onPress={() => goToProductPage(i)}
                      style={[styles.vendorPageChip, i === productPage && styles.vendorPageChipActive]}
                      testID={`vendor-page-${i + 1}`}
                    >
                      <Text style={[styles.vendorPageChipText, i === productPage && styles.vendorPageChipTextActive]}>
                        {i + 1}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </ScrollView>
                <TouchableOpacity
                  onPress={() => goToProductPage(productPage + 1)}
                  disabled={(productPage + 1) * PRODUCT_PAGE >= productTotal}
                  style={[styles.vendorPagerBtn, (productPage + 1) * PRODUCT_PAGE >= productTotal && { opacity: 0.35 }]}
                  testID="vendor-page-next"
                >
                  <Feather name="chevron-right" size={18} color={colors.primary} />
                </TouchableOpacity>
              </View>
            ) : null}
            {products.length > 0 ? (
              <Text style={styles.vendorEndNote} testID="vendor-products-end">
                Page {productPage + 1} of {Math.max(1, Math.ceil(productTotal / PRODUCT_PAGE))} · showing{" "}
                {products.length.toLocaleString("en-IN")} of {(productTotal || products.length).toLocaleString("en-IN")} products
              </Text>
            ) : null}
          </ScrollView>
        )
      )}

      {tab === "sales" && (
        sales.length === 0 ? (
          <View style={styles.center}><Feather name="trending-up" size={48} color={colors.textMuted} /><Text style={styles.emptyTitle}>No sales yet</Text></View>
        ) : (
          <FlatList
            data={sales}
            keyExtractor={(it) => it.id}
            renderItem={({ item }) => (
              <View style={styles.saleRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.saleName} numberOfLines={1}>{item.product_name}</Text>
                  <Text style={styles.saleMeta}>Order #{item.order_id.slice(0, 8)} · qty {item.qty} · {new Date(item.created_at).toLocaleDateString()}</Text>
                </View>
                <View style={{ alignItems: "flex-end" }}>
                  <Text style={styles.saleAmount}>+{formatINR(item.vendor_share)}</Text>
                  <Text style={styles.saleSub}>of {formatINR(item.line_total)}</Text>
                </View>
              </View>
            )}
            contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }}
            ItemSeparatorComponent={() => <View style={styles.sep} />}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
          />
        )
      )}

      {tab === "qa" && (
        questions.length === 0 ? (
          <View style={styles.center}>
            <Feather name="message-circle" size={48} color={colors.textMuted} />
            <Text style={styles.emptyTitle}>No customer questions yet</Text>
            <Text style={{ fontSize: 12, color: colors.textMuted, marginTop: 8, textAlign: "center", maxWidth: 280 }}>
              When customers tap "Ask vendor" on your product pages, their questions show up here.
            </Text>
          </View>
        ) : (
          <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
            <ScrollView
              contentContainerStyle={{ padding: spacing.screen, paddingBottom: 80 }}
              refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={colors.primary} />}
              keyboardShouldPersistTaps="handled"
            >
              <GradientCard variant={pendingCount > 0 ? "primary" : "emerald"} style={{ marginBottom: 14, padding: 18 }}>
                <Text style={{ fontSize: 11, letterSpacing: 2, color: "rgba(255,255,255,0.85)", fontWeight: "700" }}>QUESTIONS TO ANSWER</Text>
                <Text style={{ fontSize: 26, fontWeight: "900", color: "#fff", marginTop: 4, letterSpacing: -0.6 }}>
                  {pendingCount} pending
                </Text>
                <Text style={{ fontSize: 12, color: "rgba(255,255,255,0.9)", marginTop: 4 }}>
                  {questions.length - pendingCount} answered · responding quickly builds buyer trust
                </Text>
              </GradientCard>
              {questions.map((q) => (
                <View key={q.id} style={[styles.qaCard, q.answered ? styles.qaCardAnswered : styles.qaCardPending]}>
                  {/* Product header */}
                  <View style={styles.qaProduct}>
                    {q.product_image ? <Image source={{ uri: q.product_image }} style={styles.qaProductImg} /> : <View style={[styles.qaProductImg, { backgroundColor: colors.surfaceMuted }]} />}
                    <View style={{ flex: 1 }}>
                      <Text style={styles.qaProductName} numberOfLines={1}>{q.product_name}</Text>
                      <Text style={styles.qaMeta}>
                        Asked by {q.asker_name} · {new Date(q.created_at).toLocaleDateString()}
                      </Text>
                    </View>
                    {q.answered ? (
                      <View style={styles.qaPillDone}><Text style={styles.qaPillDoneText}>ANSWERED</Text></View>
                    ) : (
                      <View style={styles.qaPillPending}><Text style={styles.qaPillPendingText}>NEW</Text></View>
                    )}
                  </View>

                  {/* Question text */}
                  <View style={styles.qaQuestion}>
                    <Feather name="help-circle" size={14} color={colors.primary} />
                    <Text style={styles.qaQuestionText}>{q.text}</Text>
                  </View>

                  {/* Existing answers */}
                  {(q.answers || []).map((a) => (
                    <View key={a.id} style={styles.qaAnswer}>
                      <Feather name="corner-down-right" size={13} color={colors.textMuted} />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.qaAnswerMeta}>{a.by_name} · {a.by_role.toUpperCase()}</Text>
                        <Text style={styles.qaAnswerText}>{a.text}</Text>
                      </View>
                    </View>
                  ))}

                  {/* Answer input */}
                  {answeringQid === q.id ? (
                    <View style={{ marginTop: 10 }}>
                      <TextInput
                        value={answerText}
                        onChangeText={setAnswerText}
                        placeholder="Write your reply (will be public)…"
                        placeholderTextColor={colors.textMuted}
                        multiline
                        style={[styles.input, styles.area, { minHeight: 80, marginTop: 0 }]}
                        testID={`vendor-answer-input-${q.id}`}
                      />
                      <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
                        <TouchableOpacity onPress={() => { setAnsweringQid(null); setAnswerText(""); }} style={[styles.primaryBtn, { flex: 1, backgroundColor: colors.surfaceMuted, marginTop: 0 }]}>
                          <Text style={[styles.primaryBtnText, { color: colors.textMain }]}>Cancel</Text>
                        </TouchableOpacity>
                        <TouchableOpacity
                          onPress={() => onSubmitAnswer(q)}
                          disabled={submittingAnswer || !answerText.trim()}
                          style={[styles.primaryBtn, { flex: 1.4, marginTop: 0 }, (submittingAnswer || !answerText.trim()) && { opacity: 0.6 }]}
                          testID={`vendor-answer-send-${q.id}`}
                        >
                          {submittingAnswer ? <ActivityIndicator color={colors.primaryFg} /> : (
                            <>
                              <Feather name="send" size={14} color={colors.primaryFg} />
                              <Text style={styles.primaryBtnText}>  Post reply</Text>
                            </>
                          )}
                        </TouchableOpacity>
                      </View>
                    </View>
                  ) : (
                    <TouchableOpacity
                      onPress={() => { setAnsweringQid(q.id); setAnswerText(""); }}
                      style={styles.qaAnswerBtn}
                      testID={`vendor-answer-${q.id}`}
                    >
                      <Feather name={q.answered ? "plus-circle" : "edit-3"} size={14} color={colors.primary} />
                      <Text style={styles.qaAnswerBtnText}>
                        {q.answered ? "Add another reply" : "Write reply"}
                      </Text>
                    </TouchableOpacity>
                  )}
                </View>
              ))}
            </ScrollView>
          </KeyboardAvoidingView>
        )
      )}
      </View>

      <RichProductEditor
        visible={editorOpen}
        existing={editing as any}
        onClose={() => setEditorOpen(false)}
        onSaved={async () => {
          const wasLive = !!editing?.id && editing?.is_published !== false;
          setEditorOpen(false);
          await load();
          if (wasLive) {
            Alert.alert(
              "Sent for approval",
              "Your changes are saved, but the product stays hidden from the shop until an admin approves them.",
            );
          }
        }}
        endpoints={{
          create: "/vendor/me/products",
          update: (id: string) => `/vendor/me/products/${id}`,
          detail: (id: string) => `/vendor/me/products/${id}`,
        }}
        hidePublishedToggle={true}
      />

      {/* Interested customers modal */}
      <Modal visible={!!interestedFor} transparent animationType="slide" onRequestClose={() => setInterestedFor(null)}>
        <View style={styles.vendorModalOverlay}>
          <View style={styles.vendorModalSheet}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
              <Text style={styles.vendorModalTitle}>Customers waiting</Text>
              <TouchableOpacity onPress={() => setInterestedFor(null)}><Feather name="x" size={22} color={colors.textMain} /></TouchableOpacity>
            </View>
            <Text style={styles.vendorModalSub}>
              {interestedFor?.name} · {interestedUsers.length} interested
            </Text>
            {interestedLoading ? (
              <ActivityIndicator color={colors.primary} style={{ marginVertical: 24 }} />
            ) : interestedUsers.length === 0 ? (
              <Text style={{ textAlign: "center", color: colors.textMuted, paddingVertical: 24 }}>
                No customers yet — when shoppers tap “I'm interested” on the out-of-stock card, they'll show up here.
              </Text>
            ) : (
              <ScrollView style={{ maxHeight: 380 }}>
                {interestedUsers.map((u) => (
                  <View key={u.id} style={styles.vendorUserRow}>
                    <View style={styles.vendorUserAvatar}>
                      <Text style={styles.vendorUserAvatarText}>{(u.name || "?").charAt(0).toUpperCase()}</Text>
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.vendorUserName}>{u.name || "Customer"}</Text>
                      <Text style={styles.vendorUserMeta}>{u.email}{u.phone ? ` · ${u.phone}` : ""}</Text>
                    </View>
                  </View>
                ))}
              </ScrollView>
            )}
            <TouchableOpacity onPress={() => setInterestedFor(null)} style={[styles.primaryBtn, { marginTop: 14 }]}>
              <Text style={styles.primaryBtnText}>Got it</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* Jul 2026 — Earnings drill-down modal */}
      <Modal
        visible={!!earningsOpen}
        animationType="slide"
        onRequestClose={() => setEarningsOpen(null)}
      >
        <SafeAreaView style={{ flex: 1, backgroundColor: colors.background }} edges={["top"]}>
          <View style={styles.header}>
            <TouchableOpacity onPress={() => setEarningsOpen(null)} style={styles.iconBtn} testID="earn-close">
              <Feather name="x" size={22} color={colors.textMain} />
            </TouchableOpacity>
            <Text style={styles.title}>
              {earningsOpen?.scope === "today" ? "Today's Earnings" : "Lifetime Earnings"}
            </Text>
            <View style={{ width: 40 }} />
          </View>

          {/* Filter controls */}
          <View style={{ paddingHorizontal: spacing.screen, paddingBottom: 8 }}>
            <View style={{ flexDirection: "row", gap: 6, marginBottom: 8 }}>
              {(["", "online", "pos"] as const).map((c) => (
                <TouchableOpacity
                  key={c || "all"}
                  onPress={() => {
                    setEarningsChannel(c);
                    if (earningsOpen) fetchEarnings(earningsOpen.scope, earningsMonth, c);
                  }}
                  style={{
                    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 99,
                    backgroundColor: earningsChannel === c ? colors.primary : colors.surface,
                    borderWidth: 1, borderColor: earningsChannel === c ? colors.primary : colors.border,
                  }}
                  testID={`earn-ch-${c || "all"}`}
                >
                  <Text style={{ fontSize: 11, fontWeight: "800", color: earningsChannel === c ? colors.primaryFg : colors.textMain, letterSpacing: 0.4 }}>
                    {c === "" ? "ALL CHANNELS" : c === "online" ? "SHOP ORDERS" : "STORE SALE"}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            {earningsOpen?.scope === "lifetime" ? (
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                {(() => {
                  const now = new Date();
                  const opts: { key: string; label: string }[] = [{ key: "", label: "All time" }];
                  for (let i = 0; i < 6; i++) {
                    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
                    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
                    const label = d.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
                    opts.push({ key, label });
                  }
                  return opts.map((o) => {
                    const on = earningsMonth === o.key;
                    return (
                      <TouchableOpacity
                        key={o.key || "all"}
                        onPress={() => {
                          setEarningsMonth(o.key);
                          if (earningsOpen) fetchEarnings(earningsOpen.scope, o.key, earningsChannel);
                        }}
                        style={{
                          paddingHorizontal: 10, paddingVertical: 6, borderRadius: 8,
                          backgroundColor: on ? colors.brand100 : colors.surface,
                          borderWidth: 1, borderColor: on ? colors.primary : colors.border,
                        }}
                        testID={`earn-mo-${o.key || "all"}`}
                      >
                        <Text style={{ fontSize: 11, fontWeight: on ? "800" : "700", color: on ? colors.primary : colors.textMain }}>
                          {o.label}
                        </Text>
                      </TouchableOpacity>
                    );
                  });
                })()}
              </View>
            ) : null}
          </View>

          {/* Summary strip */}
          <View style={{ flexDirection: "row", justifyContent: "space-between", paddingHorizontal: spacing.screen, marginBottom: 6 }}>
            <Text style={{ fontSize: 11, fontWeight: "800", color: colors.textMuted, letterSpacing: 0.4 }}>
              {earningRows.length} TXN{earningRows.length === 1 ? "" : "S"}
            </Text>
            <Text style={{ fontSize: 14, fontWeight: "900", color: colors.primary }}>
              {formatINR(earningRows.reduce((a, r) => a + (r.line_total || 0), 0))}
            </Text>
          </View>

          {/* Rows */}
          {earningsLoading ? (
            <View style={{ padding: 40, alignItems: "center" }}>
              <ActivityIndicator color={colors.primary} />
            </View>
          ) : (
            <FlatList
              contentContainerStyle={{ padding: spacing.screen, paddingTop: 4, paddingBottom: 40 }}
              data={earningRows}
              keyExtractor={(r, i) => `${r.channel}-${r.id}-${i}`}
              renderItem={({ item }) => (
                <View style={styles.earnRow}>
                  <View style={{
                    paddingHorizontal: 6, paddingVertical: 3, borderRadius: 6,
                    backgroundColor: item.channel === "online" ? "#3B82F620" : "#10B98120",
                  }}>
                    <Text style={{
                      fontSize: 9, fontWeight: "800", letterSpacing: 0.6,
                      color: item.channel === "online" ? "#1D4ED8" : "#047857",
                    }}>{item.channel === "online" ? "SHOP" : "STORE"}</Text>
                  </View>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text style={styles.earnProduct} numberOfLines={2}>{item.product_name}</Text>
                    <Text style={styles.earnMeta}>
                      {new Date(item.created_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}
                      {item.qty ? `  ·  Qty ${item.qty}` : ""}
                      {item.invoice_no ? `  ·  ${item.invoice_no}` : (item.order_id ? `  ·  #${item.order_id.slice(0, 8).toUpperCase()}` : "")}
                    </Text>
                  </View>
                  <Text style={styles.earnAmount}>{formatINR(item.line_total)}</Text>
                </View>
              )}
              ListEmptyComponent={
                <View style={{ padding: 40, alignItems: "center" }}>
                  <Feather name="inbox" size={30} color={colors.textMuted} />
                  <Text style={{ color: colors.textMuted, marginTop: 8, fontWeight: "700", fontSize: 13 }}>
                    No earnings in this view.
                  </Text>
                  <Text style={{ color: colors.textMuted, fontSize: 11, marginTop: 4 }}>Try a different month or channel.</Text>
                </View>
              }
            />
          )}
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

function StatCard({ icon, label, value, color }: { icon: any; label: string; value: string; color: string }) {
  return (
    <View style={[styles.statCard]}>
      <View style={[styles.statIcon, { backgroundColor: color + "20" }]}><Feather name={icon} size={16} color={color} /></View>
      <Text style={styles.statLabel}>{label}</Text>
      <Text style={[styles.statValue, { color }]}>{value}</Text>
    </View>
  );
}

// Note: the legacy local ProductEditor was removed — both Admin and Vendor
// panels now share the RichProductEditor in /src/rich-product-editor.tsx so
// the vendor product form is identical to the admin form (all 7 sections:
// basics, brand/sub-features, gallery, styled summaries, attrs, spec tabs,
// what's in the box).

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.screen, paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: colors.border },
  title: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  iconBtn: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  tabsRow: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: colors.border, paddingHorizontal: spacing.screen },
  tab: { paddingVertical: 12, paddingHorizontal: 16, marginRight: 8, borderBottomWidth: 2, borderBottomColor: "transparent" },
  tabActive: { borderBottomColor: colors.primary },
  tabText: { fontSize: 13, fontWeight: "700", color: colors.textMuted },
  statsGrid: { flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between", rowGap: 10 },
  // Jun 2026 — Delivery cash summary card
  cashCard: { marginTop: 10, padding: 14, borderRadius: radii.card, backgroundColor: "#FFFBEB", borderWidth: 1, borderColor: "#FDE68A" },
  cashHeader: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 12 },
  cashTitle: { flex: 1, fontSize: 10, fontWeight: "900", color: "#92400E", letterSpacing: 1.2 },
  cashRow: { flexDirection: "row", alignItems: "flex-start" },
  cashCell: { flex: 1, gap: 3 },
  cashDivider: { width: 1, alignSelf: "stretch", backgroundColor: "#FDE68A", marginHorizontal: 10 },
  cashLabel: { fontSize: 9, fontWeight: "800", color: "#A16207", letterSpacing: 0.7 },
  cashValueDone: { fontSize: 20, fontWeight: "900", color: "#047857", letterSpacing: -0.5 },
  cashValuePending: { fontSize: 20, fontWeight: "900", color: "#B45309", letterSpacing: -0.5 },
  cashMeta: { fontSize: 10, fontWeight: "700", color: "#A16207" },
  cashHint: { fontSize: 11, fontWeight: "700", color: "#92400E", marginTop: 12, textAlign: "center" },
  statCell: { width: "48.5%" },
  statCard: { width: "100%", minHeight: 108, justifyContent: "flex-start", backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.card, padding: 14 },
  // Jul 2026 — Per-channel breakdown pills below the stats grid
  channelRow: { flexDirection: "row", gap: 10, marginTop: 12 },
  channelPill: {
    flex: 1, flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#EFF6FF", borderColor: "#DBEAFE", borderWidth: 1,
    borderRadius: 12, padding: 10,
  },
  channelPillLabel: { fontSize: 9, fontWeight: "800", letterSpacing: 0.6, color: "#1D4ED8" },
  channelPillValue: { fontSize: 15, fontWeight: "900", color: colors.textMain, marginTop: 2 },
  channelPillMeta: { fontSize: 10, color: colors.textMuted, marginTop: 1 },
  // Earnings drill-down row
  earnRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 12, marginBottom: 8,
    backgroundColor: colors.surface, borderRadius: 12,
    borderWidth: 1, borderColor: colors.border,
  },
  earnProduct: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  earnMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  earnAmount: { fontSize: 15, fontWeight: "900", color: colors.primary },
  statIcon: { width: 32, height: 32, borderRadius: 16, alignItems: "center", justifyContent: "center", marginBottom: 8 },
  statLabel: { fontSize: 9, letterSpacing: 1, color: colors.textMuted, fontWeight: "700" },
  statValue: { fontSize: 17, fontWeight: "800", marginTop: 2 },
  primaryBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", backgroundColor: colors.primary, borderRadius: radii.button, paddingVertical: 14, marginTop: 20 },
  primaryBtnText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  // Jun 2026 — catalogue backup / restore entry points (Phase 4A).
  backupBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, marginTop: 12, paddingVertical: 12, paddingHorizontal: 16, borderRadius: radii.button, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  backupBtnText: { color: colors.primary, fontWeight: "800", fontSize: 13 },
  backupRow: { flexDirection: "row", alignItems: "center", gap: 10, padding: 12, marginBottom: 12, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  backupRowTitle: { fontSize: 13.5, fontWeight: "800", color: colors.textMain },
  backupRowHint: { fontSize: 11, color: colors.textMuted, marginTop: 1 },
  vendorPager: {
    flexDirection: "row", alignItems: "center", marginTop: 4, marginBottom: 6,
    backgroundColor: colors.surface, borderRadius: radii.button,
    borderWidth: 1, borderColor: colors.border, paddingVertical: 6, paddingHorizontal: 4,
  },
  vendorPagerBtn: {
    width: 44, height: 44, borderRadius: radii.button,
    alignItems: "center", justifyContent: "center",
  },
  vendorPageChip: {
    minWidth: 44, height: 44, paddingHorizontal: 12, borderRadius: radii.button,
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceMuted, borderWidth: 1, borderColor: colors.border,
  },
  vendorPageChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  vendorPageChipText: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  vendorPageChipTextActive: { color: colors.primaryFg },
  vendorEndNote: { textAlign: "center", fontSize: 11.5, color: colors.textMuted, paddingVertical: 14 },

  prodCard: { flexDirection: "row", alignItems: "center", padding: 10, backgroundColor: colors.surface, borderRadius: radii.card, borderWidth: 1, borderColor: colors.border, gap: 10 },
  prodImg: { width: 48, height: 48, borderRadius: 8 },
  prodName: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  prodMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  emptyTitle: { fontSize: 16, fontWeight: "700", color: colors.textMain, marginTop: 12 },
  saleRow: { flexDirection: "row", alignItems: "center", paddingVertical: 12 },
  sep: { height: 1, backgroundColor: colors.border },
  saleName: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  saleMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  saleAmount: { fontSize: 14, fontWeight: "800", color: "#1F6B44" },
  saleSub: { fontSize: 10, color: colors.textMuted, marginTop: 2 },
  label: { fontSize: 12, color: colors.textMuted, marginTop: 12, marginBottom: 6, fontWeight: "600" },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border, borderRadius: radii.input, paddingHorizontal: 16, paddingVertical: 14, fontSize: 14, color: colors.textMain },
  area: { minHeight: 90, paddingTop: 14 },
  imagePreview: { width: "100%", height: 180, borderRadius: radii.card, marginBottom: 8 },
  attachBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", padding: 12, borderRadius: radii.input, borderWidth: 1, borderStyle: "dashed", borderColor: colors.border, backgroundColor: colors.surface },
  attachBtnText: { color: colors.textMain, fontSize: 13, fontWeight: "600" },
  toggleRow: { flexDirection: "row", alignItems: "center", marginTop: 16, gap: 10 },
  toggleBox: { width: 22, height: 22, borderRadius: 4, borderWidth: 2, borderColor: colors.border, alignItems: "center", justifyContent: "center" },
  toggleBoxOn: { backgroundColor: colors.primary, borderColor: colors.primary },
  toggleLabel: { fontSize: 13, color: colors.textMain, fontWeight: "600" },
  modalFooter: { padding: spacing.screen, borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.background },

  // ============================================================
  //  Phase D — Vendor product gallery (matches customer/admin look)
  // ============================================================
  vendorGrid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  vendorCard: {
    flexBasis: "48%", flexGrow: 1,
    backgroundColor: colors.surface, borderRadius: 18, overflow: "hidden",
    borderWidth: 1, borderColor: colors.border,
    ...Platform.select({
      ios: { shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 8, shadowOffset: { width: 0, height: 4 } },
      android: { elevation: 2 },
      default: {},
    }),
  },
  vendorImgWrap: { position: "relative", aspectRatio: 1, backgroundColor: colors.surfaceMuted },
  vendorImg: { width: "100%", height: "100%" },
  vendorBody: { padding: 12, gap: 4 },
  vendorCat: { fontSize: 10, fontWeight: "700", color: colors.textMuted, letterSpacing: 0.6, textTransform: "uppercase" },
  vendorName: { fontSize: 13, fontWeight: "700", color: colors.textMain, lineHeight: 17, minHeight: 34 },
  vendorFooterRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: 4 },
  vendorPrice: { fontSize: 15, fontWeight: "800", color: colors.primary, letterSpacing: -0.3 },
  vendorStockLabel: { fontSize: 10, color: colors.textMuted, fontWeight: "700" },
  vendorActions: { flexDirection: "row", gap: 8, marginTop: 10 },
  vendorActionBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 5, paddingVertical: 8, borderRadius: 10, borderWidth: 1, borderColor: colors.primary },
  vendorActionText: { fontSize: 11, fontWeight: "800", color: colors.primary },
  vendorActionDanger: { flex: 0, width: 36, paddingVertical: 8, backgroundColor: "#FCE9E5", borderColor: "#FCE9E5" },

  vendorDraftPill: { position: "absolute", top: 8, left: 8, backgroundColor: "#FFF4E5", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6 },
  vendorDraftText: { color: "#7A4A0E", fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },
  vendorOosOverlay: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, alignItems: "center", justifyContent: "center", backgroundColor: "rgba(255,255,255,0.5)" },
  vendorOosText: { fontSize: 13, fontWeight: "900", color: colors.textMain, letterSpacing: 2, backgroundColor: "rgba(255,255,255,0.85)", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 4, overflow: "hidden" },
  vendorLowStock: { position: "absolute", top: 8, left: 8, paddingVertical: 4, paddingHorizontal: 8, backgroundColor: "#F59E0B", borderRadius: 999 },
  vendorLowStockText: { fontSize: 9, fontWeight: "800", color: "#fff", letterSpacing: 0.4 },
  vendorInterestBadge: { position: "absolute", top: 8, right: 8, flexDirection: "row", alignItems: "center", gap: 4, paddingVertical: 3, paddingHorizontal: 8, backgroundColor: colors.primary, borderRadius: 999 },
  vendorInterestText: { fontSize: 10, fontWeight: "800", color: "#fff" },

  // Interested-customers modal styles
  vendorModalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  vendorModalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 24, paddingBottom: 36 },
  vendorModalTitle: { fontSize: 18, fontWeight: "800", color: colors.textMain },
  vendorModalSub: { fontSize: 12, color: colors.textMuted, marginBottom: 12 },
  vendorUserRow: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border },
  vendorUserAvatar: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  vendorUserAvatarText: { color: colors.primaryFg, fontWeight: "800", fontSize: 14 },
  vendorUserName: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  vendorUserMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },

  // ─── Tab badge (Q&A pending count) ───
  tabBadge: {
    minWidth: 18, height: 18, borderRadius: 9, paddingHorizontal: 5,
    backgroundColor: "#E11D48",
    alignItems: "center", justifyContent: "center",
  },
  tabBadgeText: { fontSize: 9, fontWeight: "900", color: "#fff", letterSpacing: 0.3 },

  // ─── Q&A cards ───
  qaCard: {
    backgroundColor: colors.surface,
    borderRadius: 16, padding: 14, marginBottom: 12,
    borderWidth: 1, borderColor: colors.border,
  },
  qaCardPending: { borderLeftWidth: 4, borderLeftColor: "#E11D48" },
  qaCardAnswered: { borderLeftWidth: 4, borderLeftColor: "#16A34A" },
  qaProduct: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 10 },
  qaProductImg: { width: 44, height: 44, borderRadius: 10 },
  qaProductName: { fontSize: 13, fontWeight: "800", color: colors.textMain },
  qaMeta: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  qaPillPending: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, backgroundColor: "#E11D48" },
  qaPillPendingText: { fontSize: 9, fontWeight: "900", color: "#fff", letterSpacing: 0.7 },
  qaPillDone: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, backgroundColor: "#DCFCE7" },
  qaPillDoneText: { fontSize: 9, fontWeight: "900", color: "#166534", letterSpacing: 0.7 },
  qaQuestion: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    padding: 12, borderRadius: 12, backgroundColor: colors.surfaceMuted,
  },
  qaQuestionText: { flex: 1, fontSize: 13, color: colors.textMain, lineHeight: 18, fontWeight: "600" },
  qaAnswer: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    marginTop: 10, paddingLeft: 6,
  },
  qaAnswerMeta: { fontSize: 10, fontWeight: "800", color: colors.textMuted, letterSpacing: 0.5 },
  qaAnswerText: { fontSize: 13, color: colors.textMain, lineHeight: 18, marginTop: 2 },
  qaAnswerBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    marginTop: 10, paddingVertical: 10, borderRadius: 10,
    borderWidth: 1, borderColor: colors.primary,
    backgroundColor: colors.primary + "10",
  },
  qaAnswerBtnText: { fontSize: 12, fontWeight: "800", color: colors.primary },
});
