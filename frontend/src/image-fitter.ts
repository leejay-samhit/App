/**
 * Smart image fitter for Shop Layout blocks.
 *
 * Why: the previous picker used `allowsEditing: true` which forced every
 * source image into a 1:1 square crop regardless of the destination block —
 * banners ended up distorted and category circles ended up with off-centre
 * subjects. This module replaces that with a per-block-type fit pipeline:
 *
 *   pick (no edit)  →  center-crop to the block's native aspect ratio
 *                  →  downscale to the recommended pixel resolution
 *                  →  JPEG-compress to ~75 % quality
 *                  →  return as a data: URL (base64) the API already speaks.
 *
 * Callers pass the block_type (e.g. "banner_slider") or one of the
 * fine-grained `ImageTarget` keys for product images, vendor logos etc.
 * The fitter handles centre-crop math itself so the user gets a perfect
 * fit on the first try — no in-app crop screen.
 */
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { Alert, Platform } from "react-native";

// ── Target catalogue ──────────────────────────────────────────────────
// width/height = the FINAL pixel resolution we save at. The aspect ratio
// is derived from these. Keep these in sync with the renderer dimensions
// in /src/shop-layout-renderer.tsx and /(tabs)/shop.tsx.
export type ImageTarget =
  | "banner_slider"
  | "background"
  | "category_circles"
  | "brand_slider"
  | "offer_cards"
  | "content_box"
  | "product_image"
  | "product_thumb"
  | "vendor_logo"
  | "broadcast_image";

type Spec = { width: number; height: number; label: string };

export const IMAGE_SPECS: Record<ImageTarget, Spec> = {
  banner_slider:    { width: 1080, height: 600, label: "Banner 16:9 · 1080 × 600" },
  background:       { width: 1080, height: 400, label: "Hero 27:10 · 1080 × 400" },
  category_circles: { width:  400, height: 400, label: "Square · 400 × 400" },
  brand_slider:     { width:  540, height: 300, label: "Brand 9:5 · 540 × 300" },
  offer_cards:      { width:  600, height: 600, label: "Square · 600 × 600" },
  content_box:      { width:  800, height: 600, label: "4:3 · 800 × 600" },
  product_image:    { width:  800, height: 800, label: "Square · 800 × 800" },
  product_thumb:    { width:  400, height: 400, label: "Square · 400 × 400" },
  vendor_logo:      { width:  400, height: 400, label: "Square · 400 × 400" },
  broadcast_image:  { width: 1080, height: 540, label: "2:1 · 1080 × 540" },
};

export function specFor(target: ImageTarget): Spec { return IMAGE_SPECS[target]; }
export function aspectFor(target: ImageTarget): number {
  const s = IMAGE_SPECS[target];
  return s.width / s.height;
}

/**
 * Pick + auto-fit an image for a given block / target. Never throws — on
 * permission denial / cancellation it returns null and surfaces an Alert.
 *
 * `fitMode` controls how we shape the picked image before compressing:
 *   "cover"   (default) — CENTRE-CROP to the block's native aspect ratio
 *                         then resize to the recommended pixel size.
 *                         Result: image fills the block, edges may crop.
 *   "contain" — NO CROP. Resize the source so its longest edge equals the
 *                         corresponding spec side, preserving the source
 *                         aspect ratio. Result: the whole image is
 *                         visible; the block is letterboxed by the
 *                         renderer's background color.
 */
export async function pickAndFitImage(
  target: ImageTarget,
  fitMode: "cover" | "contain" = "cover",
): Promise<string | null> {
  try {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert("Permission needed", "Please allow photo library access to upload an image.");
      return null;
    }

    // ⚠️ allowsEditing INTENTIONALLY off — we do the crop ourselves to the
    // exact block aspect so the user doesn't get a forced 1:1 cropper.
    const r = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      quality: 1,
      allowsEditing: false,
      exif: false,
    });
    if (r.canceled || !r.assets?.[0]?.uri) return null;
    const asset = r.assets[0];
    return await fitToTarget(asset.uri, target, asset.width, asset.height, fitMode);
  } catch (e: any) {
    Alert.alert("Couldn't load image", e?.message || "Try a different file.");
    return null;
  }
}

/**
 * Centre-crop + resize an existing image URI to the target spec and return
 * it as a `data:image/jpeg;base64,…` URL. The crop math:
 *
 *   sourceAspect > targetAspect → image is wider than block → crop sides
 *   sourceAspect < targetAspect → image is taller than block → crop top/bottom
 *
 * The crop is always centred. If we can't read the source dimensions (some
 * gallery providers strip them on Android) we fall back to a width-only
 * resize and let the renderer's `resizeMode="cover"` handle the rest.
 */
export async function fitToTarget(
  uri: string,
  target: ImageTarget,
  srcW?: number,
  srcH?: number,
  fitMode: "cover" | "contain" = "cover",
): Promise<string> {
  const spec = IMAGE_SPECS[target];
  const targetAspect = spec.width / spec.height;

  let w = srcW;
  let h = srcH;
  // Some pickers return 0/undefined dims — measure manually.
  if (!w || !h) {
    try {
      const dims = await measureImage(uri);
      w = dims.width; h = dims.height;
    } catch { /* fall through to width-only resize */ }
  }

  const actions: ImageManipulator.Action[] = [];
  if (fitMode === "contain") {
    // NO CROP. Scale so the source fits INSIDE spec.width × spec.height
    // keeping its own aspect ratio. Renderer must use resizeMode="contain"
    // + a bg color so the frame doesn't leave a visible letterbox gap.
    if (w && h) {
      const srcAspect = w / h;
      let outW: number; let outH: number;
      if (srcAspect >= targetAspect) {
        // Source wider than block — cap width.
        outW = Math.min(spec.width, w);
        outH = Math.round(outW / srcAspect);
      } else {
        // Source taller than block — cap height.
        outH = Math.min(spec.height, h);
        outW = Math.round(outH * srcAspect);
      }
      actions.push({ resize: { width: outW, height: outH } });
    } else {
      // Unknown dims — fall back to a width-only resize; renderer will still
      // "contain" the source into the block so nothing gets cropped.
      actions.push({ resize: { width: spec.width } });
    }
  } else if (w && h) {
    // "cover" mode — centre-crop to target aspect then resize.
    const srcAspect = w / h;
    if (Math.abs(srcAspect - targetAspect) > 0.005) {
      // Need a centre crop.
      let cropW: number; let cropH: number;
      if (srcAspect > targetAspect) {
        // Source is wider — keep height, narrow width.
        cropH = h;
        cropW = Math.round(h * targetAspect);
      } else {
        cropW = w;
        cropH = Math.round(w / targetAspect);
      }
      const originX = Math.max(0, Math.round((w - cropW) / 2));
      const originY = Math.max(0, Math.round((h - cropH) / 2));
      actions.push({ crop: { originX, originY, width: cropW, height: cropH } });
    }
    actions.push({ resize: { width: spec.width, height: spec.height } });
  } else {
    // "cover" fallback with unknown dims — width-only resize.
    actions.push({ resize: { width: spec.width, height: spec.height } });
  }

  const out = await ImageManipulator.manipulateAsync(uri, actions, {
    compress: 0.75,
    format: ImageManipulator.SaveFormat.JPEG,
    base64: true,
  });
  if (!out.base64) throw new Error("manipulator returned no base64");
  return `data:image/jpeg;base64,${out.base64}`;
}

// Cross-platform Image.getSize wrapper. Returns a promise so we can await
// inside fitToTarget.
function measureImage(uri: string): Promise<{ width: number; height: number }> {
  // ImageManipulator.manipulateAsync with no actions just decodes the image
  // and returns its real size — works on iOS / Android / web.
  return ImageManipulator.manipulateAsync(uri, [], { compress: 1 }).then((r) => ({
    width: r.width, height: r.height,
  })).catch(() => {
    if (Platform.OS === "web") {
      // Fallback for older Expo Web versions.
      return new Promise((resolve, reject) => {
        const img = new (globalThis as any).Image();
        img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
        img.onerror = () => reject(new Error("img load failed"));
        img.src = uri;
      });
    }
    throw new Error("could not measure image");
  });
}
