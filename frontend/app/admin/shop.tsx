/**
 * Admin · Shop tab
 *
 * Reuses the customer-facing <ShopHome /> component so an admin can browse
 * the store exactly as a user would (live products, banners, layout blocks,
 * etc). Adds a small admin-only quick action card at the top that links to
 * the management screens (Products, Shop layout, Shop categories).
 */
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather, MaterialCommunityIcons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { ShopHome } from "../../src/shop-home";
import { useAuth } from "../../src/auth";
import { SCOPED_ADMIN_ROLES } from "../../src/admin-roles";
import { colors } from "../../src/theme";
import { useDoubleTapExit } from "../../src/use-double-tap-exit";

export default function AdminShop() {
  const router = useRouter();
  const { user } = useAuth();
  // A scoped manager may open this screen to cross-check the live shop, so
  // only show the quick-manage chips their role can actually use.
  const role = String((user as any)?.admin_role || "super_admin");
  const can = (area: "products" | "layout" | "categories" | "orders") => {
    if (!SCOPED_ADMIN_ROLES.includes(role)) return true;
    if (role === "products_manager") return area === "products" || area === "categories";
    if (role === "layout_manager") return area === "layout" || area === "categories";
    if (role === "order_manager") return area === "orders";
    return false;
  };
  // Shop is now the admin's landing tab — apply double-tap-back to exit
  // (Indian-app standard, replaces the old 3-option popup).
  useDoubleTapExit();

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      {/* Admin quick-manage bar — only visible to admin */}
      <View style={styles.adminBar}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.adminBarRow}>
          {can("products") ? (
          <TouchableOpacity
            style={styles.adminChip}
            onPress={() => router.push("/admin/products")}
            testID="admin-shop-products"
          >
            <Feather name="package" size={13} color={colors.primaryFg} />
            <Text style={styles.adminChipText}>Products</Text>
          </TouchableOpacity>
          ) : null}
          {can("layout") ? (
          <TouchableOpacity
            style={[styles.adminChip, { backgroundColor: "#7C3AED" }]}
            onPress={() => router.push("/admin/shop-layout")}
            testID="admin-shop-layout"
          >
            <Feather name="layout" size={13} color="#fff" />
            <Text style={styles.adminChipText}>Layout</Text>
          </TouchableOpacity>
          ) : null}
          {can("categories") ? (
          <TouchableOpacity
            style={[styles.adminChip, { backgroundColor: "#F59E0B" }]}
            onPress={() => router.push("/admin/shop-categories")}
            testID="admin-shop-categories"
          >
            <MaterialCommunityIcons name="shape-outline" size={13} color="#fff" />
            <Text style={styles.adminChipText}>Categories</Text>
          </TouchableOpacity>
          ) : null}
          {can("orders") ? (
          <TouchableOpacity
            style={[styles.adminChip, { backgroundColor: "#0EA5E9" }]}
            onPress={() => router.push("/admin/orders")}
            testID="admin-shop-orders"
          >
            <Feather name="shopping-bag" size={13} color="#fff" />
            <Text style={styles.adminChipText}>Orders</Text>
          </TouchableOpacity>
          ) : null}
        </ScrollView>
      </View>

      {/* Customer view — embedded with admin-route prefix so tapping a
          category card pushes /admin/shop-category/<name> (and the admin
          bottom-tab bar stays visible) instead of jumping into the
          (tabs) layout. */}
      <View style={{ flex: 1 }}>
        <ShopHome cartCount={0} wishlistCount={0} categoryRoutePrefix="/admin" />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  adminBar: {
    backgroundColor: colors.background,
    borderBottomWidth: 1, borderBottomColor: colors.border + "55",
    paddingVertical: 8,
  },
  adminBarRow: {
    flexDirection: "row",
    gap: 8,
    paddingHorizontal: 12,
  },
  adminChip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8,
    backgroundColor: colors.primary,
    borderRadius: 999,
  },
  adminChipText: {
    color: "#fff",
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 0.2,
  },
});
