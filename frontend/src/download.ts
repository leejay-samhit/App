import { Platform, Alert } from "react-native";
// Use legacy API for cacheDirectory/writeAsStringAsync/EncodingType — still supported in v55.
import * as FileSystem from "expo-file-system/legacy";
import * as Sharing from "expo-sharing";

/**
 * Save a text payload (CSV / JSON / etc.) to the device. On web it triggers a
 * browser download via a blob + anchor click. On native (iOS/Android) it
 * writes to the cache directory and presents the share sheet so the user can
 * save it to Files / Drive / etc.
 */
export async function downloadText(opts: {
  filename: string;
  content: string;
  mimeType?: string;
}): Promise<{ ok: boolean; method: "browser" | "share"; path?: string }> {
  const { filename, content, mimeType = "text/csv" } = opts;

  if (Platform.OS === "web") {
    try {
      // Use the global Blob + URL APIs — these exist in the web preview Metro renders.
      const blob = new Blob([content], { type: `${mimeType};charset=utf-8;` });
      // @ts-ignore — window/document are available on web only
      const url = window.URL.createObjectURL(blob);
      // @ts-ignore
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.style.display = "none";
      // @ts-ignore
      document.body.appendChild(a);
      a.click();
      // @ts-ignore
      document.body.removeChild(a);
      // Revoke after a tick so Safari/iOS Safari has time to use it.
      setTimeout(() => {
        try {
          // @ts-ignore
          window.URL.revokeObjectURL(url);
        } catch {}
      }, 1500);
      return { ok: true, method: "browser" };
    } catch (e: any) {
      Alert.alert("Download failed", e?.message || "Could not start the file download.");
      return { ok: false, method: "browser" };
    }
  }

  // Native: write to cache then open share sheet.
  try {
    const dir = (FileSystem as any).cacheDirectory || (FileSystem as any).documentDirectory;
    if (!dir) throw new Error("No writable directory available");
    const path = `${dir}${filename}`;
    await FileSystem.writeAsStringAsync(path, content, {
      encoding: FileSystem.EncodingType.UTF8,
    });
    const sharingAvailable = await Sharing.isAvailableAsync();
    if (sharingAvailable) {
      await Sharing.shareAsync(path, { mimeType, dialogTitle: filename });
    } else {
      Alert.alert("Saved", `File saved to: ${path}`);
    }
    return { ok: true, method: "share", path };
  } catch (e: any) {
    Alert.alert("Save failed", e?.message || "Could not save the export.");
    return { ok: false, method: "share" };
  }
}
