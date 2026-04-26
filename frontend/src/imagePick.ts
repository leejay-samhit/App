// Lightweight helpers around expo-image-picker + expo-image-manipulator.
// Returns a base64 data URL string (e.g. "data:image/jpeg;base64,...") suitable for upload.
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { Alert, Platform } from "react-native";

const MAX_WIDTH = 1280;
const COMPRESS = 0.6;

async function ensureLibraryPerm(): Promise<boolean> {
  if (Platform.OS === "web") return true;
  const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (status !== "granted") {
    Alert.alert("Permission needed", "Please allow photo library access to upload images.");
    return false;
  }
  return true;
}

async function ensureCameraPerm(): Promise<boolean> {
  if (Platform.OS === "web") return true;
  const { status } = await ImagePicker.requestCameraPermissionsAsync();
  if (status !== "granted") {
    Alert.alert("Permission needed", "Please allow camera access to take photos.");
    return false;
  }
  return true;
}

async function processToBase64(uri: string): Promise<string> {
  const manipulated = await ImageManipulator.manipulateAsync(
    uri,
    [{ resize: { width: MAX_WIDTH } }],
    { compress: COMPRESS, format: ImageManipulator.SaveFormat.JPEG, base64: true }
  );
  if (!manipulated.base64) throw new Error("Failed to read image");
  return `data:image/jpeg;base64,${manipulated.base64}`;
}

export async function pickFromLibrary(): Promise<string | null> {
  if (!(await ensureLibraryPerm())) return null;
  const res = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ImagePicker.MediaTypeOptions.Images,
    quality: 0.9,
    allowsEditing: false,
    base64: false,
  });
  if (res.canceled || !res.assets?.[0]?.uri) return null;
  return processToBase64(res.assets[0].uri);
}

export async function takePhoto(): Promise<string | null> {
  if (!(await ensureCameraPerm())) return null;
  const res = await ImagePicker.launchCameraAsync({
    mediaTypes: ImagePicker.MediaTypeOptions.Images,
    quality: 0.9,
    allowsEditing: false,
    base64: false,
  });
  if (res.canceled || !res.assets?.[0]?.uri) return null;
  return processToBase64(res.assets[0].uri);
}
