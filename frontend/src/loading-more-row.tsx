// Nov 2026 — footer shown while the next page of a long catalogue loads.
import { View, Text, ActivityIndicator, StyleSheet } from "react-native";
import { colors } from "./theme";

export function LoadingMoreRow() {
  return (
    <View style={styles.row} testID="loading-more">
      <ActivityIndicator size="small" color={colors.primary} />
      <Text style={styles.text}>Loading more products…</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 8, paddingVertical: 18,
  },
  text: { fontSize: 12.5, fontWeight: "700", color: colors.textMuted },
});
