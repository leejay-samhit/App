// Legacy route — the file backup now lives as a tab inside
// Admin → Data backups, so old links / bookmarks land in the right place.
import { Redirect } from "expo-router";

export default function AdminBackupFileRedirect() {
  return <Redirect href="/admin/backups" />;
}
