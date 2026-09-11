/**
 * Notification settings — Profile → Notifications.
 *
 * Each switch maps 1:1 to a push category the backend checks before it calls
 * the relay (see routes/push.py::filter_by_prefs). Everything is ON by
 * default; turning one off silences BOTH the phone push and the bell row for
 * that category.
 *
 * The "New order received" switch only exists for approved sellers.
 */
import { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  ActivityIndicator, Switch, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Feather } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as Linking from "expo-linking";

import { api, formatApiError } from "../src/api";
import { useAuth } from "../src/auth";
import { colors, radii, spacing } from "../src/theme";
import { notify } from "../src/notify";

type PrefKey = "orders" | "chats" | "offers" | "login_alerts" | "vendor_new_order";
type Prefs = Record<PrefKey, boolean>;

const ROWS: { key: PrefKey; icon: any; title: string; sub: string; vendorOnly?: boolean }[] = [
  {
    key: "orders", icon: "package", title: "Order updates",
    sub: "Confirmed, shipped, out for delivery and delivered",
  },
  {
    key: "chats", icon: "message-circle", title: "Chat messages",
    sub: "Replies from sellers, support and the team",
  },
  {
    key: "offers", icon: "tag", title: "Offers & announcements",
    sub: "Deals, new arrivals and app news",
  },
  {
    key: "login_alerts", icon: "shield", title: "New device login alerts",
    sub: "Told the moment your account signs in somewhere new",
  },
  {
    key: "vendor_new_order", icon: "shopping-bag", title: "New order received",
    sub: "Ping me the second a customer places an order", vendorOnly: true,
  },
];

export default function NotificationSettingsScreen() {
  const router = useRouter();
  // Wait for the session to hydrate — on a cold deep-link the token is still
  // being read from storage, and firing the request early just 401s.
  const { user } = useAuth();
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [isVendor, setIsVendor] = useState(false);
  const [saving, setSaving] = useState<PrefKey | null>(null);

  const load = useCallback(async (retry = true) => {
    try {
      const { data } = await api.get<{ prefs: Prefs; is_vendor: boolean }>("/me/notification-prefs");
      setPrefs(data.prefs);
      setIsVendor(!!data.is_vendor);
    } catch (e: any) {
      // Cold deep-link (e.g. tapped from a push): the session may still be
      // hydrating from storage, so a 401 on the first try isn't fatal.
      if (retry && e?.response?.status === 401) {
        setTimeout(() => load(false), 1500);
        return;
      }
      notify("Couldn't load your settings", formatApiError(e));
    }
  }, []);

  useEffect(() => { load(); }, [load, user?.id]);

  const toggle = async (key: PrefKey, value: boolean) => {
    if (!prefs) return;
    const before = prefs;
    setPrefs({ ...prefs, [key]: value });   // optimistic
    setSaving(key);
    try {
      const { data } = await api.put<{ prefs: Prefs }>("/me/notification-prefs", { [key]: value });
      setPrefs(data.prefs);
    } catch (e) {
      setPrefs(before);                     // roll back on failure
      notify("Couldn't save", formatApiError(e));
    } finally { setSaving(null); }
  };

  const rows = ROWS.filter((r) => !r.vendorOnly || isVendor);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => router.back()} style={styles.backBtn} testID="notif-back">
          <Feather name="arrow-left" size={22} color={colors.textMain} />
        </TouchableOpacity>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>Notifications</Text>
          <Text style={styles.sub}>Choose what reaches your phone</Text>
        </View>
      </View>

      {!prefs ? (
        <View style={styles.center}><ActivityIndicator color={colors.primary} /></View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: spacing.screen, paddingBottom: 48 }}>
          <View style={styles.card}>
            {rows.map((r, i) => (
              <View key={r.key}>
                {i > 0 ? <View style={styles.divider} /> : null}
                <View style={styles.row} testID={`notif-row-${r.key}`}>
                  <View style={styles.iconWrap}>
                    <Feather name={r.icon} size={17} color={colors.primary} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowTitle}>{r.title}</Text>
                    <Text style={styles.rowSub}>{r.sub}</Text>
                  </View>
                  {saving === r.key ? (
                    <ActivityIndicator size="small" color={colors.primary} style={{ width: 44 }} />
                  ) : (
                    <Switch
                      value={prefs[r.key]}
                      onValueChange={(v) => toggle(r.key, v)}
                      trackColor={{ true: colors.primary, false: colors.border }}
                      testID={`notif-switch-${r.key}`}
                    />
                  )}
                </View>
              </View>
            ))}
          </View>

          <Text style={styles.note}>
            Turning a switch off stops both the phone notification and the in-app
            bell for that type. Order updates are worth keeping on — it&apos;s how you
            know a parcel is on its way.
          </Text>

          {Platform.OS !== "web" ? (
            <TouchableOpacity
              onPress={() => { Linking.openSettings().catch(() => {}); }}
              style={styles.settingsBtn}
              testID="notif-open-settings"
            >
              <Feather name="external-link" size={16} color={colors.primary} />
              <Text style={styles.settingsBtnText}>Sounds & phone permissions</Text>
            </TouchableOpacity>
          ) : null}
          <Text style={styles.note}>
            Chat messages arrive on their own notification channel, so you can give
            them a different sound or vibration from order updates in your phone&apos;s
            notification settings.
          </Text>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 12, paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface,
  },
  backBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center" },
  h1: { fontSize: 18, fontWeight: "900", color: colors.textMain, letterSpacing: -0.3 },
  sub: { fontSize: 11.5, color: colors.textMuted, marginTop: 1 },
  card: {
    backgroundColor: colors.surface, borderRadius: radii.card,
    borderWidth: 1, borderColor: colors.border, paddingHorizontal: 14,
  },
  row: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 14, minHeight: 64 },
  iconWrap: {
    width: 34, height: 34, borderRadius: 10, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.primary + "14",
  },
  rowTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain },
  rowSub: { fontSize: 11.5, color: colors.textMuted, marginTop: 2, lineHeight: 16 },
  divider: { height: 1, backgroundColor: colors.border },
  note: { fontSize: 11.5, color: colors.textMuted, lineHeight: 17, marginTop: 14 },
  settingsBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    marginTop: 16, minHeight: 48, borderRadius: radii.button,
    borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.primary + "10",
  },
  settingsBtnText: { fontSize: 13.5, fontWeight: "800", color: colors.primary },
});
