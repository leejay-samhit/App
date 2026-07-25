// Shared rich Amazon/Flipkart-style product editor used by BOTH the Admin
// (`/admin/products`) and the Vendor (`/vendor/dashboard`) panels.
//
// Why a shared component?  Earlier the two panels had divergent forms — the
// admin had the full 7-section rich editor while the vendor only had a basic
// name/price/image form, so vendors couldn't enter brand/sub-features/gallery/
// specs/etc.  Sharing one component keeps both panels in lock-step forever.
//
// The component is parameterized by `endpoints` which is the only difference
// between admin and vendor (admin posts to `/admin/products`, vendor posts to
// `/vendor/me/products`).

import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Alert, Modal,
  TextInput, ScrollView, Switch, Image, KeyboardAvoidingView, Platform,
} from "react-native";
import { Feather } from "@expo/vector-icons";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import { api, formatApiError } from "./api";
import { colors, radii } from "./theme";
import { useAuth } from "./auth";
import { BarcodeScannerModal, type ScannerTarget } from "./barcode-scanner-modal";

// ── Types ──
export type StyledText = { text?: string; bold?: boolean; font_size?: number | null; align?: "left" | "center" | "right" };
export type SpecRow = { label: string; value: string };
export type SpecTab = { name: string; rows: SpecRow[] };
export type BoxItem = { name: string; image_data_url: string };

export type RichProduct = {
  id?: string; name?: string; price?: number; stock?: number;
  image_url?: string; description?: string; category?: string; is_published?: boolean;
  brand?: string; sub_features?: string[]; images?: string[];
  price_summary?: StyledText; protection_summary?: StyledText;
  warranty_summary?: StyledText; delivery_summary?: StyledText;
  attrs_brand?: string; attrs_os?: string; attrs_ram?: string;
  attrs_cpu_model?: string; attrs_cpu_speed?: string; attrs_storage?: string;
  extra_attrs?: Record<string, string>;
  spec_tabs?: SpecTab[]; whats_in_box?: BoxItem[];
  // Clothes-specific
  sub_category?: string; // male | female | boys | girls
  clothing_size?: string; // S | M | L | XL | XXL
};

// Predefined category options. The last value ("Other") lets the user
// type any custom category.
const CATEGORY_OPTIONS = [
  "Electronics", "Mobiles", "Laptop", "Clothes", "Shoes", "Accessories", "Other",
] as const;
const CLOTHES_SUB_OPTIONS = [
  { key: "male", label: "Male (Men)" },
  { key: "female", label: "Female (Women)" },
  { key: "boys", label: "Boys (Kids)" },
  { key: "girls", label: "Girls (Kids)" },
] as const;
const CLOTHES_SIZE_OPTIONS = ["S", "M", "L", "XL", "XXL"] as const;

export type RichProductEndpoints = {
  /** Endpoint to POST the JSON payload for CREATE (e.g. "/admin/products"). */
  create: string;
  /** Function that returns the PATCH endpoint for UPDATE for a given id. */
  update: (id: string) => string;
};

const emptyStyled = (): StyledText => ({ text: "", bold: false, font_size: null, align: "left" });

/**
 * Luhn checksum — the industry-standard IMEI validation (also used by credit
 * cards). A valid 15-digit IMEI passes the following algorithm:
 *   1. Starting from the rightmost digit, double every second digit.
 *   2. If a doubled value has two digits (>=10), sum its digits (or subtract 9).
 *   3. Sum all resulting digits. Result must be a multiple of 10.
 *
 * We accept `null`/empty as VALID because the field is optional. Anything with
 * non-digit chars is coerced by stripping them first.
 *
 * References: https://en.wikipedia.org/wiki/Luhn_algorithm  •  ITU-T E.212
 */
export function isValidImei(raw: string | null | undefined): boolean {
  if (!raw) return true;                               // optional field
  const digits = String(raw).replace(/\D/g, "");
  if (digits.length !== 15) return false;              // IMEI must be 15 digits
  let sum = 0;
  for (let i = 0; i < 15; i++) {
    let n = parseInt(digits[i], 10);
    if ((15 - i) % 2 === 0) {                          // "every second from right"
      n *= 2;
      if (n > 9) n -= 9;
    }
    sum += n;
  }
  return sum % 10 === 0;
}

async function pickAndCompressImage(opts?: { aspect?: [number, number]; width?: number }) {
  // Delegate to the smart fitter so product hero images get a clean centre-crop
  // to the recommended 1:1 800×800 spec. Square is the default for product
  // photography (matches the gallery + grid renderers). The legacy
  // aspect/width opts are kept for backward compat but no longer honoured —
  // callers that need a different ratio should switch to pickAndFitImage().
  const { pickAndFitImage } = await import("./image-fitter");
  void opts;
  return await pickAndFitImage("product_image");
}

// ─── Internal helpers (collapsible section + styled-text editor) ───

function Section({ title, icon, summary, defaultOpen, children, testID }: {
  title: string; icon: any; summary?: string; defaultOpen?: boolean; children: React.ReactNode; testID?: string;
}) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <View style={sectionStyles.wrap}>
      <TouchableOpacity onPress={() => setOpen(!open)} style={sectionStyles.head} activeOpacity={0.7} testID={testID}>
        <View style={sectionStyles.headIcon}><Feather name={icon} size={16} color={colors.primary} /></View>
        <View style={{ flex: 1 }}>
          <Text style={sectionStyles.headTitle}>{title}</Text>
          {summary ? <Text style={sectionStyles.headSummary} numberOfLines={1}>{summary}</Text> : null}
        </View>
        <Feather name={open ? "chevron-up" : "chevron-down"} size={18} color={colors.textMuted} />
      </TouchableOpacity>
      {open ? <View style={sectionStyles.body}>{children}</View> : null}
    </View>
  );
}

function StyledTextEditor({ value, onChange, placeholder, testID }: {
  value: StyledText; onChange: (next: StyledText) => void; placeholder?: string; testID?: string;
}) {
  return (
    <View>
      <TextInput
        value={value.text || ""}
        onChangeText={(t) => onChange({ ...value, text: t })}
        placeholder={placeholder}
        placeholderTextColor={colors.textMuted}
        multiline
        style={[modalStyles.input, { minHeight: 60, paddingTop: 12 }]}
        testID={testID}
      />
      <View style={sectionStyles.toolRow}>
        <TouchableOpacity
          onPress={() => onChange({ ...value, bold: !value.bold })}
          style={[sectionStyles.toolBtn, value.bold && sectionStyles.toolBtnActive]}
        >
          <Feather name="bold" size={13} color={value.bold ? colors.primaryFg : colors.textMain} />
        </TouchableOpacity>
        {(["left", "center", "right"] as const).map((al) => (
          <TouchableOpacity
            key={al}
            onPress={() => onChange({ ...value, align: al })}
            style={[sectionStyles.toolBtn, value.align === al && sectionStyles.toolBtnActive]}
          >
            <Feather name={al === "left" ? "align-left" : al === "center" ? "align-center" : "align-right"} size={13} color={value.align === al ? colors.primaryFg : colors.textMain} />
          </TouchableOpacity>
        ))}
        {[12, 14, 16, 18, 22].map((sz) => (
          <TouchableOpacity
            key={sz}
            onPress={() => onChange({ ...value, font_size: value.font_size === sz ? null : sz })}
            style={[sectionStyles.toolBtn, value.font_size === sz && sectionStyles.toolBtnActive, { paddingHorizontal: 8 }]}
          >
            <Text style={{ fontSize: 10, fontWeight: "700", color: value.font_size === sz ? colors.primaryFg : colors.textMain }}>{sz}</Text>
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );
}

// ─── Main component ───

export function RichProductEditor({
  visible, existing, onClose, onSaved, endpoints, hidePublishedToggle,
}: {
  visible: boolean;
  existing: RichProduct | null;
  onClose: () => void;
  onSaved: () => void;
  endpoints: RichProductEndpoints;
  /** UPDATE 1 (June 2026) — Vendors no longer control publish state; the
   *  publish toggle is admin-only. Pass true from the vendor dashboard to
   *  hide the switch AND stop sending `is_published` to the server (the
   *  backend forces false on vendor create + strips it from PATCH). */
  hidePublishedToggle?: boolean;
}) {
  // Role-gate the AI image generator. Only SUPER ADMIN sees the AI block.
  // Vendors must post product images manually. This protects the single
  // shared Emergent LLM Key budget from being drained by many vendors.
  const { user } = useAuth();
  const canUseAI = (user?.role || "").toLowerCase() === "admin";

  // ── Basics ──
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [stock, setStock] = useState("100");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [published, setPublished] = useState(true);
  // ── Brand + sub-features ──
  const [brand, setBrand] = useState("");
  const [subFeatures, setSubFeatures] = useState<string[]>([]);
  const [newSubFeature, setNewSubFeature] = useState("");
  // ── Gallery ──
  const [galleryImages, setGalleryImages] = useState<string[]>([]);
  // ── Styled summaries ──
  const [priceSummary, setPriceSummary] = useState<StyledText>(emptyStyled());
  const [protectionSummary, setProtectionSummary] = useState<StyledText>(emptyStyled());
  const [warrantySummary, setWarrantySummary] = useState<StyledText>(emptyStyled());
  const [deliverySummary, setDeliverySummary] = useState<StyledText>(emptyStyled());
  // ── Attributes ──
  const [attrsBrand, setAttrsBrand] = useState("");
  const [attrsOs, setAttrsOs] = useState("");
  const [attrsRam, setAttrsRam] = useState("");
  const [attrsCpuModel, setAttrsCpuModel] = useState("");
  const [attrsCpuSpeed, setAttrsCpuSpeed] = useState("");
  const [attrsStorage, setAttrsStorage] = useState("");
  const [extraAttrs, setExtraAttrs] = useState<{ key: string; value: string }[]>([]);
  // ── Spec Tabs ──
  const [specTabs, setSpecTabs] = useState<SpecTab[]>([]);
  // ── What's in the box ──
  const [whatsInBox, setWhatsInBox] = useState<BoxItem[]>([]);
  // ── Clothes-specific ──
  const [subCategory, setSubCategory] = useState<string>(""); // male|female|boys|girls
  const [clothingSize, setClothingSize] = useState<string>("");
  // ── Device identity (July 2026) — Serial + IMEI-1 + IMEI-2 ──
  // Optional across ALL products.  IMEIs are validated client-side with a
  // Luhn checksum (industry-standard 15-digit ID for phones).  Backend
  // just stores whatever the frontend accepts — no rejection.
  const [serialNumber, setSerialNumber] = useState<string>("");
  const [imei1, setImei1] = useState<string>("");
  const [imei2, setImei2] = useState<string>("");
  // ── UPDATE 3 (August 2026) — Barcode scanner target + spec-not-found hint ──
  const [scannerTarget, setScannerTarget] = useState<ScannerTarget | null>(null);
  const [specsNotFoundHint, setSpecsNotFoundHint] = useState<string>("");
  // ── AI Reference image (NOT shown in product gallery — used only to
  // prompt the AI). Kept separate from cover/gallery so the original
  // reference can be re-used by the "Regenerate" button.
  const [aiReference, setAiReference] = useState<string>("");
  // Selected AI style chips: plain | highlight | outdoor | activity | accessory
  const [aiStyles, setAiStyles] = useState<string[]>(["plain"]);
  // Whether the current cover/gallery were last produced by the AI.
  // When true we show the "Regenerate" CTA.
  const [aiProduced, setAiProduced] = useState<boolean>(false);
  // Track whether the user picked a preset category or chose "Other"
  // Now uses admin-managed categories (falls back to bootstrapped list).
  const isPresetCat = (c: string) => {
    const cl = (c || "").trim().toLowerCase();
    if (!cl || cl === "other") return false;
    return adminCategories.some((x) => x.toLowerCase() === cl)
        || (CATEGORY_OPTIONS as readonly string[]).some((x) => x.toLowerCase() === cl);
  };
  const [customCategory, setCustomCategory] = useState<boolean>(false);

  const [saving, setSaving] = useState(false);
  const [picking, setPicking] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);

  // ── June 2026 — Dynamic category sync from Admin ──
  // Previously the vendor category chips were hardcoded (Electronics /
  // Mobiles / Laptop / Clothes / Shoes / Accessories / Other).  Per
  // user directive the mobile app now pulls the admin-managed shop
  // categories list at runtime so add/delete on the admin side is
  // instantly reflected in the vendor product form.
  //
  // Nov 2026 upgrade — categories are now a NESTED tree.  We fetch the
  // full tree so the vendor can pick a parent category first and then
  // a subcategory (if any exist).
  type CatNode = {
    id: string;
    name: string;
    parent_id?: string | null;
    children?: CatNode[];
  };
  const [categoryTree, setCategoryTree] = useState<CatNode[]>([]);
  const [adminCategories, setAdminCategories] = useState<string[]>([]);
  useEffect(() => {
    if (!visible) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get<{ items: CatNode[] }>("/shop-categories/tree");
        if (cancelled) return;
        setCategoryTree(r.data?.items || []);
        // Flatten root names for the chip picker (parents only — subs
        // are picked in a second dropdown below).
        setAdminCategories((r.data?.items || []).map((c) => c.name));
      } catch {
        if (!cancelled) { setAdminCategories([]); setCategoryTree([]); }
      }
    })();
    return () => { cancelled = true; };
  }, [visible]);
  // Merged category list: admin-managed first, always fall back to the
  // baked-in defaults so the picker is never empty on a fresh install
  // or offline load.
  const categoryChips: string[] = React.useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const c of adminCategories) {
      const key = c.trim();
      if (key && !seen.has(key.toLowerCase())) {
        out.push(key); seen.add(key.toLowerCase());
      }
    }
    // Ensure "Other" is always the last option so the vendor can type a
    // custom category if the admin catalog doesn't cover it yet.
    if (!seen.has("other")) out.push("Other");
    return out;
  }, [adminCategories]);
  // Nov 2026 — Subcategory chips derived from the picked parent.
  const subcategoryChips: string[] = React.useMemo(() => {
    if (!category || customCategory) return [];
    const target = category.trim().toLowerCase();
    const walk = (nodes: CatNode[]): CatNode | null => {
      for (const n of nodes) {
        if ((n.name || "").trim().toLowerCase() === target) return n;
        if (n.children && n.children.length) {
          const inner = walk(n.children);
          if (inner) return inner;
        }
      }
      return null;
    };
    const found = walk(categoryTree);
    return (found?.children || []).map((c) => c.name);
  }, [category, categoryTree, customCategory]);

  // ── UPDATE 2 (June 2026) — Smart product-master autocomplete ──
  //
  // Vendors typing a product name here get a live typeahead of matching
  // catalog entries. Tapping a match auto-fills EVERY field so a vendor can
  // list a phone in ~10 seconds instead of 5 minutes.
  //
  // Behaviour:
  //   • Only shown when `hidePublishedToggle` is true (i.e. the vendor
  //     dashboard, not the admin one — admins build the master and don't
  //     need to look it up).
  //   • Debounced 300ms per keystroke.
  //   • 60-second in-memory cache keyed by normalised query so re-typing
  //     the same word doesn't re-hit the network.
  //   • Suggestions dropdown appears BELOW the search input.
  //   • Tapping a result runs `applyMasterMatch(row)` which patches every
  //     downstream state field in one go.
  const showMasterSearch = !!hidePublishedToggle;
  const [masterQuery, setMasterQuery] = useState("");
  const [masterResults, setMasterResults] = useState<any[]>([]);
  const [masterOpen, setMasterOpen] = useState(false);
  const [masterBusy, setMasterBusy] = useState(false);
  const [masterExternalHint, setMasterExternalHint] = useState<string>("");
  // UPDATE 2b — Source filter chips: "all" | "local" (Slangcart) | "91mobiles" | "deodap"
  // Lets the vendor scope results to just our catalog or a specific
  // external one when Smart Search merges multiple providers.
  const [masterSource, setMasterSource] = useState<"all" | "local" | "91mobiles" | "deodap">("all");
  const masterCacheRef = React.useRef<Map<string, { at: number; items: any[]; external: boolean }>>(new Map());
  const masterDebounceRef = React.useRef<any>(null);

  // Sept 2026 — Free image picker (DuckDuckGo→Openverse→Wikimedia
  // fallback under the hood).  Owner asked for a "Google Images style"
  // picker for grocery / regional-Indian products that have no
  // 91mobiles or Deodap entry.  Opens as a bottom-sheet modal.
  const [imgPickerOpen, setImgPickerOpen] = useState(false);
  const [imgPickerQuery, setImgPickerQuery] = useState("");
  const [imgPickerBusy, setImgPickerBusy] = useState(false);
  const [imgPickerResults, setImgPickerResults] = useState<Array<{
    image: string; thumbnail: string; title: string; source: string;
    provider: string; width?: number | null; height?: number | null; license: string;
  }>>([]);
  const [imgPickerResolvedQuery, setImgPickerResolvedQuery] = useState("");
  const [imgPickerErr, setImgPickerErr] = useState<string>("");
  const [imgPickerSelected, setImgPickerSelected] = useState<Set<string>>(new Set());

  // Debounced search. 300ms after the last keystroke we hit the backend
  // (or the in-memory cache if the same query fired in the last 60s).
  useEffect(() => {
    if (!showMasterSearch) return;
    if (masterDebounceRef.current) clearTimeout(masterDebounceRef.current);
    const q = masterQuery.trim();
    if (q.length < 2) {
      setMasterResults([]);
      setMasterOpen(false);
      setMasterBusy(false);
      return;
    }
    masterDebounceRef.current = setTimeout(async () => {
      const key = q.toLowerCase();
      const now = Date.now();
      const cached = masterCacheRef.current.get(key);
      if (cached && now - cached.at < 60_000) {
        setMasterResults(cached.items);
        setMasterOpen(true);
        setMasterBusy(false);
        setMasterExternalHint(cached.external ? "" : cached.items.length === 0 ? "No match found — you can enter this manually below." : "");
        return;
      }
      setMasterBusy(true);
      try {
        const r = await api.get<any>("/products/master/search", { params: { q, limit: 10 } });
        const items: any[] = r.data?.items || [];
        const external: boolean = !!r.data?.external_available;
        masterCacheRef.current.set(key, { at: now, items, external });
        setMasterResults(items);
        setMasterOpen(true);
        setMasterExternalHint(items.length === 0 ? "No match found — you can enter this manually below." : "");
      } catch {
        setMasterResults([]);
        setMasterExternalHint("Couldn't reach the catalog. Enter details manually below.");
        setMasterOpen(true);
      } finally { setMasterBusy(false); }
    }, 300);
    return () => { if (masterDebounceRef.current) clearTimeout(masterDebounceRef.current); };
  }, [masterQuery, showMasterSearch]);

  /**
   * Apply a master-catalog match to the form. Only touches empty fields by
   * default so partially-filled forms don't wipe the vendor's work — pass
   * `overwrite=true` for a clean apply on brand-new products.
   */
  const applyMasterMatch = (row: any, overwrite: boolean = true) => {
    const put = (setter: (v: any) => void, currentEmpty: boolean, next: any) => {
      if (overwrite || currentEmpty) setter(next);
    };
    put(setName, !name.trim(), row.name || "");
    put(setPrice, !price.trim(), row.price ? String(row.price) : "");
    put(setImageUrl, !imageUrl, row.image_url || "");
    put(setDescription, !description.trim(), row.description || "");
    if (row.category) {
      const preset = isPresetCat(row.category);
      put(setCategory, !category.trim(), row.category);
      setCustomCategory(!preset);
    }
    put(setBrand, !brand.trim(), row.brand || "");
    put(setSubFeatures, subFeatures.length === 0, Array.isArray(row.sub_features) ? row.sub_features : []);
    put(setGalleryImages, galleryImages.length === 0, Array.isArray(row.images) ? row.images.filter(Boolean) : []);
    if (row.price_summary) put(setPriceSummary, !priceSummary.text, row.price_summary);
    if (row.protection_summary) put(setProtectionSummary, !protectionSummary.text, row.protection_summary);
    if (row.warranty_summary) put(setWarrantySummary, !warrantySummary.text, row.warranty_summary);
    if (row.delivery_summary) put(setDeliverySummary, !deliverySummary.text, row.delivery_summary);
    put(setAttrsBrand, !attrsBrand.trim(), row.attrs_brand || row.brand || "");
    put(setAttrsOs, !attrsOs.trim(), row.attrs_os || "");
    put(setAttrsRam, !attrsRam.trim(), row.attrs_ram || "");
    put(setAttrsCpuModel, !attrsCpuModel.trim(), row.attrs_cpu_model || "");
    put(setAttrsCpuSpeed, !attrsCpuSpeed.trim(), row.attrs_cpu_speed || "");
    put(setAttrsStorage, !attrsStorage.trim(), row.attrs_storage || "");
    const extras = row.extra_attrs || {};
    if (extras && typeof extras === "object") {
      put(setExtraAttrs, extraAttrs.length === 0, Object.entries(extras).map(([k, v]) => ({ key: k, value: String(v) })));
    }
    if (Array.isArray(row.spec_tabs) && row.spec_tabs.length) {
      put(setSpecTabs, specTabs.length === 0, row.spec_tabs);
    }
    if (Array.isArray(row.whats_in_box) && row.whats_in_box.length) {
      put(setWhatsInBox, whatsInBox.length === 0, row.whats_in_box);
    }
    // UPDATE 2c — When picking a 91mobiles result, auto-load the 91mobiles
    // spec template so the vendor sees the exact same column structure buyers
    // will recognise on 91mobiles. We do this AFTER field patches so any
    // sniffed values (brand/model/RAM/storage) prefill their cells.
    if (row.source === "91mobiles" && specTabs.length === 0) {
      // Defer to next tick so React commits the field-setter batch first,
      // giving loadM91Template the fresh brand/RAM/etc. values.
      setTimeout(() => loadM91Template("merge"), 0);
    }
    // Aug 2026 v2 — Fast image pre-fetch.  In PARALLEL with the full spec
    // scrape above, fire the lightweight `/91mobiles-detail` endpoint which
    // returns just { hero_image, gallery } from GSMArena.  Because both
    // requests share the brand-catalog cache, this typically resolves ~800ms
    // before the full specs endpoint — so the vendor sees the HD product
    // image populated immediately after picking, instead of staring at a
    // low-res 91mobiles thumbnail while specs load.
    if (row.source === "91mobiles") {
      (async () => {
        try {
          const q = (row.name || "").trim();
          const b = (row.brand || row.attrs_brand || "").trim();
          if (q.length < 2) return;
          const d = await api.get<any>("/products/master/91mobiles-detail", {
            params: { name: q, ...(b ? { brand: b } : {}) },
          });
          const heroImg: string = d?.data?.hero_image || "";
          const gal: string[] = Array.isArray(d?.data?.gallery) ? d.data.gallery : [];
          // Only patch fields the user hasn't touched — respects any
          // manual edits between pick and this async resolution.
          if (heroImg) {
            setImageUrl((cur) => cur || heroImg);
          }
          if (gal.length > 0) {
            setGalleryImages((cur) => {
              if (cur.length > 0) return cur;  // vendor already edited
              const withHero = heroImg && !gal.includes(heroImg) ? [heroImg, ...gal] : gal;
              return withHero.slice(0, 12);
            });
          }
        } catch { /* silent — full spec scrape will populate images if this failed */ }
      })();
    }
    // Aug 2026 — Deodap enrichment: the autosuggest API only ships 1 tiny
    // thumbnail per product.  When the vendor actually PICKS the row we
    // fire /products/master/deodap-detail to pull the full HD gallery
    // (typically 5-12 photos) and merge them into galleryImages.
    if (row.source === "deodap" && row.handle) {
      (async () => {
        try {
          const d = await api.get<any>("/products/master/deodap-detail", { params: { handle: row.handle } });
          const imgs: string[] = (d?.data?.images || []).filter(Boolean);
          if (imgs.length > 0) {
            // Replace the low-res cover with the FIRST HD image so the
            // "Main Display pic" the admin sees is sharp.
            setImageUrl(imgs[0]);
            setGalleryImages(imgs.slice(0, 12));
          }
          if (d?.data?.description && !description.trim()) {
            setDescription(String(d.data.description).slice(0, 2000));
          }
        } catch { /* silent — vendor still has the thumbnail + can add images */ }
      })();
    }
    // Collapse the dropdown but keep the query so the vendor sees what they picked.
    setMasterOpen(false);
    setMasterQuery(row.name || "");
  };

  // Hydrate when modal opens (or when switching to a different product)
  useEffect(() => {
    if (!visible) return;
    setName(existing?.name || "");
    setPrice(existing?.price ? String(existing.price) : "");
    setStock(existing?.stock != null ? String(existing.stock) : "100");
    setDescription(existing?.description || "");
    setCategory(existing?.category || "");
    setImageUrl(existing?.image_url || "");
    setPublished(existing?.is_published !== false);
    const e = (existing || {}) as any;
    setBrand(e.brand || "");
    setSubFeatures(Array.isArray(e.sub_features) ? e.sub_features : []);
    setGalleryImages(Array.isArray(e.images) ? e.images : []);
    setPriceSummary(e.price_summary || emptyStyled());
    setProtectionSummary(e.protection_summary || emptyStyled());
    setWarrantySummary(e.warranty_summary || emptyStyled());
    setDeliverySummary(e.delivery_summary || emptyStyled());
    setAttrsBrand(e.attrs_brand || "");
    setAttrsOs(e.attrs_os || "");
    setAttrsRam(e.attrs_ram || "");
    setAttrsCpuModel(e.attrs_cpu_model || "");
    setAttrsCpuSpeed(e.attrs_cpu_speed || "");
    setAttrsStorage(e.attrs_storage || "");
    setExtraAttrs(Object.entries(e.extra_attrs || {}).map(([k, v]) => ({ key: k, value: String(v) })));
    setSpecTabs(Array.isArray(e.spec_tabs) ? e.spec_tabs.map((t: any) => ({ name: t.name || "", rows: Array.isArray(t.rows) ? t.rows : [] })) : []);
    setWhatsInBox(Array.isArray(e.whats_in_box) ? e.whats_in_box : []);
    setNewSubFeature("");
    setSubCategory(e.sub_category || "");
    setClothingSize(e.clothing_size || "");
    setSerialNumber((e as any).serial_number || "");
    setImei1((e as any).imei_1 || "");
    setImei2((e as any).imei_2 || "");
    // Reset AI state — reference image is never persisted on the product.
    setAiReference("");
    setAiProduced(false);
    setAiStyles(["plain"]);
    // UPDATE 2 — Reset smart-search state whenever the modal opens.
    setMasterQuery("");
    setMasterResults([]);
    setMasterOpen(false);
    setMasterBusy(false);
    setMasterExternalHint("");
    setMasterSource("all");
    // If editing an existing product with a custom (non-preset) category,
    // open the free-text input automatically.
    setCustomCategory(!!e.category && !isPresetCat(e.category));
  }, [visible, existing?.id]);

  const onPickCover = async () => {
    // June 2026 — allow the vendor to either take a fresh photo with the
    // camera OR pick one from the gallery.  Previously only gallery was
    // supported.  Camera is the natural choice for many small-shop
    // vendors who don't keep a stock photo library.
    if (Platform.OS === "web") {
      // Web has no reliable camera capture — go straight to gallery.
      setPicking(true);
      try {
        const data = await pickAndCompressImage({ aspect: [4, 3], width: 900 });
        if (data) setImageUrl(data);
      } catch (e) {
        Alert.alert("Image pick failed", formatApiError(e));
      } finally { setPicking(false); }
      return;
    }
    Alert.alert(
      "Add cover image",
      "Take a fresh photo or pick one from your gallery.",
      [
        {
          text: "Take photo",
          onPress: async () => {
            setPicking(true);
            try {
              const perm = await ImagePicker.requestCameraPermissionsAsync();
              if (!perm.granted) {
                Alert.alert("Camera needed", "Please allow camera access to take a photo.");
                return;
              }
              const r = await ImagePicker.launchCameraAsync({
                mediaTypes: ImagePicker.MediaTypeOptions.Images,
                quality: 0.9,
                allowsEditing: false,
                exif: false,
              });
              if (r.canceled || !r.assets?.[0]?.uri) return;
              const asset = r.assets[0];
              const { fitToTarget } = await import("./image-fitter");
              const fitted = await fitToTarget(
                asset.uri, "product_image",
                asset.width, asset.height, "cover",
              );
              if (fitted) setImageUrl(fitted);
            } catch (e) {
              Alert.alert("Camera failed", formatApiError(e));
            } finally { setPicking(false); }
          },
        },
        {
          text: "Choose from gallery",
          onPress: async () => {
            setPicking(true);
            try {
              const data = await pickAndCompressImage({ aspect: [4, 3], width: 900 });
              if (data) setImageUrl(data);
            } catch (e) {
              Alert.alert("Image pick failed", formatApiError(e));
            } finally { setPicking(false); }
          },
        },
        { text: "Cancel", style: "cancel" },
      ],
    );
  };

  const onAddGalleryImage = async () => {
    if (galleryImages.length >= 10) {
      Alert.alert("Limit reached", "You can upload up to 10 gallery images.");
      return;
    }
    try {
      const data = await pickAndCompressImage({ aspect: [1, 1], width: 1000 });
      if (data) setGalleryImages([...galleryImages, data]);
    } catch (e) {
      Alert.alert("Image pick failed", formatApiError(e));
    }
  };

  // Sept 2026 — Free image picker.  Wraps the backend
  // `/products/images/search` endpoint (Openverse + Wikimedia CC).
  // Fetches on Enter / search-button tap only (not while typing) so we
  // don't hammer the API when the vendor is mid-word.
  const runFreeImageSearch = async (query?: string) => {
    const q = (query ?? imgPickerQuery).trim();
    if (q.length < 1) {
      setImgPickerErr("Type a query first — e.g. sugar, jaggery, urad dal.");
      return;
    }
    setImgPickerErr("");
    setImgPickerBusy(true);
    setImgPickerResults([]);
    setImgPickerSelected(new Set());
    try {
      const r = await api.get<any>("/products/images/search", { params: { q, limit: 30 } });
      const items = Array.isArray(r.data?.items) ? r.data.items : [];
      setImgPickerResults(items);
      setImgPickerResolvedQuery(r.data?.resolved_query || q);
      if (items.length === 0) setImgPickerErr("No results — try a simpler English term.");
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setImgPickerErr(typeof detail === "string" ? detail : "Search failed. Try again.");
    } finally { setImgPickerBusy(false); }
  };

  // Sept 2026 v2 — Route thumbnail fetches through our backend proxy so
  // Wikimedia's hotlink policy + missing CORS headers don't break render.
  // The proxy is auth-guarded and only allow-lists CC image hosts.
  const proxiedImageUrl = (u: string): string => {
    if (!u) return u;
    // Base URL that api.ts uses (EXPO_BACKEND_URL/api).  Reuse the axios
    // instance's baseURL so we hit the same origin the token is valid on.
    const base = (api.defaults.baseURL || "").replace(/\/+$/, "");
    return `${base}/products/images/proxy?url=${encodeURIComponent(u)}`;
  };

  // Apply the picker's selection to the product form: first picked item
  // becomes the cover if empty, all picks get appended to the gallery
  // (respecting the 10-image cap).  Uses the backend batch fetch endpoint
  // to avoid CORS issues on RN Web when Wikimedia doesn't send ACAO.
  const applyImagePickerSelection = async () => {
    const picks = imgPickerResults.filter((r) => imgPickerSelected.has(r.image));
    if (picks.length === 0) return;
    setImgPickerBusy(true);
    setImgPickerErr("");
    try {
      // Only download up to the number of gallery slots we have left,
      // plus 1 extra for the cover (if empty). No point paying for
      // images the vendor can't store.
      const roomForGallery = Math.max(0, 10 - galleryImages.length);
      const needCover = !imageUrl;
      const wanted = picks.slice(0, roomForGallery + (needCover ? 1 : 0));
      if (wanted.length === 0) {
        setImgPickerErr("Gallery is full (10/10). Remove a photo first.");
        return;
      }
      const r = await api.post<any>("/products/images/fetch-to-data", {
        // Sept 2026 fix — send each pick's thumbnail as a fallback so a
        // dead upstream Flickr photo (which happens surprisingly often in
        // Openverse's index) doesn't cause the whole download to fail.
        // The thumbnail is served from Openverse's own CDN so it's stable
        // even when the source disappears.
        urls: wanted.map((p) => ({ url: p.image, fallback_url: p.thumbnail })),
      });
      const items: Array<{ data_url: string | null; ok: boolean }> = r.data?.items || [];
      const dataUrls = items.map((it) => (it.ok ? it.data_url : null)).filter(Boolean) as string[];
      if (dataUrls.length === 0) {
        setImgPickerErr("Couldn't download any of the selected images. Try different picks or search again.");
        return;
      }
      // Cover: first data URL if the cover slot is empty.
      let toGallery = dataUrls;
      if (needCover) {
        setImageUrl(dataUrls[0]);
        toGallery = dataUrls.slice(1);
      }
      if (toGallery.length > 0) {
        setGalleryImages((prev) => {
          const room = Math.max(0, 10 - prev.length);
          return [...prev, ...toGallery.slice(0, room)];
        });
      }
      // Nice-to-have: report partial failures inline before closing.
      const failed = items.length - dataUrls.length - (needCover ? 1 : 0);
      if (failed > 0) {
        setImgPickerErr(`${dataUrls.length} added · ${failed} failed to download.`);
        // Keep modal open a second so the vendor sees the summary.
        setTimeout(() => { setImgPickerOpen(false); setImgPickerSelected(new Set()); }, 1200);
      } else {
        setImgPickerOpen(false);
        setImgPickerSelected(new Set());
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setImgPickerErr(typeof detail === "string" ? detail : "Download failed. Please try again.");
    } finally { setImgPickerBusy(false); }
  };



  const onAddSubFeature = () => {
    const t = newSubFeature.trim();
    if (!t) return;
    setSubFeatures([...subFeatures, t]);
    setNewSubFeature("");
  };

  const onAddExtraAttr = () => setExtraAttrs([...extraAttrs, { key: "", value: "" }]);
  const onAddSpecTab = () => setSpecTabs([...specTabs, { name: `Tab ${specTabs.length + 1}`, rows: [] }]);

  // UPDATE 2c (June 2026) — 91mobiles spec template. Populates spec_tabs with
  // the exact category structure 91mobiles uses on its mobile-phone detail
  // pages so a vendor's listing matches the look-and-feel buyers see there.
  // Values are left BLANK for the vendor to fill (we don't have detail-page
  // data yet — Cloudflare blocks scraping).  If the vendor already picked a
  // 91mobiles autosuggest row we prefill the handful of fields we DO know
  // (brand, model, RAM/storage sniffed from the name).
  const M91_SPEC_TEMPLATE: { name: string; rows: { label: string; value: string }[] }[] = [
    { name: "General", rows: [
      { label: "Launch Date", value: "" },
      { label: "Operating System", value: "" },
      { label: "Custom UI", value: "" },
      { label: "SIM Slot(s)", value: "" },
      { label: "SIM Size", value: "" },
      { label: "Network", value: "" },
      { label: "Model", value: "" },
      { label: "Brand", value: "" },
    ]},
    { name: "Design", rows: [
      { label: "Height", value: "" },
      { label: "Width", value: "" },
      { label: "Thickness", value: "" },
      { label: "Weight", value: "" },
      { label: "Build Material", value: "" },
      { label: "Colours", value: "" },
      { label: "Waterproof", value: "" },
      { label: "Ruggedness", value: "" },
    ]},
    { name: "Display", rows: [
      { label: "Screen Size", value: "" },
      { label: "Screen Resolution", value: "" },
      { label: "Pixel Density", value: "" },
      { label: "Display Type", value: "" },
      { label: "Refresh Rate", value: "" },
      { label: "Touch Screen", value: "" },
      { label: "Screen-to-Body Ratio", value: "" },
      { label: "Screen Protection", value: "" },
    ]},
    { name: "Performance", rows: [
      { label: "Chipset", value: "" },
      { label: "CPU", value: "" },
      { label: "Architecture", value: "" },
      { label: "Fabrication", value: "" },
      { label: "Graphics", value: "" },
      { label: "RAM", value: "" },
      { label: "RAM Type", value: "" },
    ]},
    { name: "Storage", rows: [
      { label: "Internal Memory", value: "" },
      { label: "Expandable Memory", value: "" },
      { label: "USB OTG", value: "" },
    ]},
    { name: "Rear Camera", rows: [
      { label: "Main Camera Resolution", value: "" },
      { label: "Sensor Size", value: "" },
      { label: "Optical Zoom", value: "" },
      { label: "Autofocus", value: "" },
      { label: "Flash", value: "" },
      { label: "Video Recording", value: "" },
      { label: "OIS", value: "" },
      { label: "Camera Features", value: "" },
    ]},
    { name: "Front Camera", rows: [
      { label: "Front Camera Resolution", value: "" },
      { label: "Aperture", value: "" },
      { label: "Video Recording", value: "" },
      { label: "Front Flash", value: "" },
    ]},
    { name: "Battery", rows: [
      { label: "Capacity", value: "" },
      { label: "Type", value: "" },
      { label: "Removable", value: "" },
      { label: "Quick Charging", value: "" },
      { label: "Wireless Charging", value: "" },
      { label: "USB Type-C", value: "" },
    ]},
    { name: "Connectivity", rows: [
      { label: "Network Support", value: "" },
      { label: "5G Bands", value: "" },
      { label: "4G Bands", value: "" },
      { label: "VoLTE", value: "" },
      { label: "Wi-Fi", value: "" },
      { label: "Bluetooth", value: "" },
      { label: "GPS", value: "" },
      { label: "NFC", value: "" },
      { label: "USB Connectivity", value: "" },
    ]},
    { name: "Sensors", rows: [
      { label: "Fingerprint Sensor", value: "" },
      { label: "Fingerprint Position", value: "" },
      { label: "Face Unlock", value: "" },
      { label: "Accelerometer", value: "" },
      { label: "Gyroscope", value: "" },
      { label: "Proximity", value: "" },
      { label: "Compass", value: "" },
      { label: "Barometer", value: "" },
    ]},
    { name: "Multimedia", rows: [
      { label: "Audio Jack", value: "" },
      { label: "Loudspeaker", value: "" },
      { label: "Speaker", value: "" },
      { label: "Dolby Audio", value: "" },
    ]},
  ];

  /**
   * Load the 91mobiles-style spec template into `specTabs`.
   *
   * UPDATED (August 2026) — Now fetches REAL values from the backend
   * `/products/master/91mobiles-specs` endpoint (which scrapes GSMArena
   * because 91mobiles' detail pages are Cloudflare-locked). Falls back to
   * the empty template with prefilled attrs if the network hop fails.
   *
   *   mode="merge"   → keep existing tabs, append missing categories
   *   mode="replace" → wipe existing tabs, populate fresh (used by "Replace" btn)
   */
  const loadM91Template = async (mode: "merge" | "replace" = "merge") => {
    // Build the empty/attrs-prefilled template first — that's our baseline
    // if the network fetch fails.
    const emptyFilled = M91_SPEC_TEMPLATE.map((t) => ({
      name: t.name,
      rows: t.rows.map((r) => {
        const l = r.label.toLowerCase();
        let v = r.value;
        if (l === "brand" && (brand || attrsBrand)) v = brand || attrsBrand;
        else if (l === "model" && name) v = name;
        else if (l === "ram" && attrsRam) v = attrsRam;
        else if (l === "internal memory" && attrsStorage) v = attrsStorage;
        else if (l === "operating system" && attrsOs) v = attrsOs;
        else if (l === "chipset" && attrsCpuModel) v = attrsCpuModel;
        else if (l === "cpu" && attrsCpuModel) v = attrsCpuModel;
        return { label: r.label, value: v };
      }),
    }));

    // Fire the API — we ONLY do this when there's enough to identify a
    // product (name + brand, or a rich name that carries the brand).
    const queryName = (masterQuery || name || "").trim();
    const queryBrand = (brand || attrsBrand || "").trim();
    let filled = emptyFilled;
    let apiSucceeded = false;
    if (queryName.length >= 2) {
      try {
        setAiBusy(true);  // reuse the "busy" indicator
        const r = await api.get<any>("/products/master/91mobiles-specs", {
          params: { name: queryName, ...(queryBrand ? { brand: queryBrand } : {}) },
        });
        const tabs: any[] = r.data?.spec_tabs || [];
        if (tabs.length > 0) {
          apiSucceeded = true;
          setSpecsNotFoundHint("");
          // UPDATE 3 — Pull HD gallery + hero image from GSMArena.
          const heroImg: string = r.data?.hero_image || "";
          const gallery: string[] = Array.isArray(r.data?.gallery) ? r.data.gallery : [];
          if (heroImg && !imageUrl) setImageUrl(heroImg);
          if (gallery.length > 0 && galleryImages.length === 0) {
            // Add heroImg first if it's not already in the gallery, then the
            // gallery photos.  Cap at 12 total.
            const withHero = heroImg && !gallery.includes(heroImg) ? [heroImg, ...gallery] : gallery;
            setGalleryImages(withHero.slice(0, 12));
          }
          // Merge API values into our labels — API returns tabs+labels in the
          // same order as `M91_SPEC_TEMPLATE`, but we still lookup by name to
          // survive future re-ordering.
          filled = M91_SPEC_TEMPLATE.map((t) => {
            const apiTab = tabs.find((x) => (x?.name || "").toLowerCase() === t.name.toLowerCase());
            return {
              name: t.name,
              rows: t.rows.map((r) => {
                const apiRow = apiTab?.rows?.find((rr: any) => (rr?.label || "").toLowerCase() === r.label.toLowerCase());
                const attrsRow = emptyFilled
                  .find((x) => x.name === t.name)?.rows
                  .find((rr) => rr.label === r.label);
                return { label: r.label, value: (apiRow?.value || attrsRow?.value || "") };
              }),
            };
          });
        } else {
          // API returned empty spec_tabs — surface the not-found hint.
          setSpecsNotFoundHint(`Specs not found for "${queryName}" — please enter manually.`);
          filled = emptyFilled;
        }
      } catch (err: any) {
        // 404 or network error — surface the hint.
        const status = err?.response?.status;
        if (status === 404) {
          setSpecsNotFoundHint(`Specs not found for "${queryName}" — please enter manually.`);
        } else {
          setSpecsNotFoundHint("Couldn't reach the spec catalog. Please enter manually.");
        }
        filled = emptyFilled;
      } finally { setAiBusy(false); }
    } else {
      setSpecsNotFoundHint("");
    }
    // A short-lived success indicator would be nice but even better: clear
    // the hint if a subsequent call succeeded (already handled above).
    void apiSucceeded;

    if (mode === "replace" || specTabs.length === 0) {
      setSpecTabs(filled);
    } else {
      // MERGE: keep existing tabs, append template tabs that aren't already there (by name)
      const existingNames = new Set(specTabs.map((t) => t.name.toLowerCase().trim()));
      const additions = filled.filter((t) => !existingNames.has(t.name.toLowerCase().trim()));
      setSpecTabs([...specTabs, ...additions]);
    }
  };
  const onAddSpecRow = (idx: number) => {
    const next = [...specTabs];
    next[idx] = { ...next[idx], rows: [...next[idx].rows, { label: "", value: "" }] };
    setSpecTabs(next);
  };

  const onAddBoxItem = async () => {
    try {
      const data = await pickAndCompressImage({ aspect: [1, 1], width: 400 });
      setWhatsInBox([...whatsInBox, { name: "", image_data_url: data || "" }]);
    } catch (e) {
      Alert.alert("Image pick failed", formatApiError(e));
    }
  };

  // ── AI Image Generation (Clothes only) ──
  const isClothes = (category || "").trim().toLowerCase() === "clothes";
  const [aiProgress, setAiProgress] = useState<{ done: number; total: number } | null>(null);

  const AI_STYLES = [
    { key: "plain",     label: "Plain",     hint: "Catalog studio" },
    { key: "highlight", label: "Highlight", hint: "In a group" },
    { key: "outdoor",   label: "Outdoor",   hint: "Scenic backdrop" },
    { key: "activity",  label: "Activity",  hint: "Gym / cycling / dancing" },
    { key: "accessory", label: "Accessory", hint: "Styled with gadgets" },
  ] as const;

  const toggleStyle = (key: string) => {
    setAiStyles((prev) => {
      const has = prev.includes(key);
      if (has) {
        // don't allow zero selected — keep at least Plain
        const next = prev.filter((k) => k !== key);
        return next.length ? next : ["plain"];
      }
      return [...prev, key];
    });
  };

  // Distribute TARGET (=5) images across selected styles as evenly as possible.
  // Examples:
  //  1 style  → [5]
  //  2 styles → [3, 2]
  //  3 styles → [2, 2, 1]
  //  4 styles → [2, 1, 1, 1]
  //  5 styles → [1, 1, 1, 1, 1]
  const distributeStyles = (total: number, styleKeys: string[]): string[] => {
    if (!styleKeys.length) return new Array(total).fill("plain");
    const n = styleKeys.length;
    const base = Math.floor(total / n);
    const remainder = total % n;
    const seq: string[] = [];
    styleKeys.forEach((k, i) => {
      const slots = base + (i < remainder ? 1 : 0);
      for (let j = 0; j < slots; j++) seq.push(k);
    });
    return seq;
  };

  const runAIGeneration = async (sourceB64: string) => {
    setAiBusy(true);
    const TARGET = 5;
    const styleSeq = distributeStyles(TARGET, aiStyles);
    setAiProgress({ done: 0, total: TARGET });
    const collected: string[] = [];
    try {
      for (let i = 0; i < TARGET; i++) {
        const style = styleSeq[i] || "plain";
        try {
          const res: any = await api.post(
            "/products/ai-image",
            {
              image_data_url: sourceB64,
              gender: subCategory,
              category: "Clothes",
              size: clothingSize || undefined,
              count: 1,
              style,
            },
            { timeout: 90000 },
          );
          const imgs: string[] = Array.isArray(res?.data?.images) ? res.data.images : [];
          if (imgs.length) {
            collected.push(imgs[0]);
            // Live-update — first image becomes cover, rest become gallery.
            // The original reference image is NOT shown in the product gallery.
            if (collected.length === 1) {
              setImageUrl(imgs[0]);
              setGalleryImages([]);
            } else {
              setGalleryImages(collected.slice(1, 10));
            }
          }
        } catch (innerErr) {
          // eslint-disable-next-line no-console
          console.warn("AI image #" + i + " failed:", formatApiError(innerErr));
        }
        setAiProgress({ done: i + 1, total: TARGET });
      }
      if (!collected.length) {
        Alert.alert(
          "AI generation failed",
          "No images could be generated. Please try a clearer reference photo or check your network and try again.",
        );
        return;
      }
      setAiProduced(true);
      Alert.alert(
        "Done",
        `Generated ${collected.length} of ${TARGET} AI image${collected.length === 1 ? "" : "s"}. Cover + gallery have been replaced.`,
      );
    } finally {
      setAiBusy(false);
      setAiProgress(null);
    }
  };

  const onGenerateAI = async () => {
    if (!isClothes) return;
    if (!subCategory) {
      Alert.alert("Pick a sub-category", "Please select Male, Female, Boys or Girls first.");
      return;
    }
    if (!aiStyles.length) {
      Alert.alert("Pick at least one style", "Tap one or more style chips (Plain, Outdoor, Activity, etc).");
      return;
    }
    // Pick a reference photo if we don't have one yet — separate from cover.
    let ref = aiReference;
    if (!ref) {
      try {
        const data = await pickAndCompressImage({ aspect: [3, 4], width: 900 });
        if (!data) return;
        ref = data;
        setAiReference(data);
      } catch (e) {
        Alert.alert("Image pick failed", formatApiError(e));
        return;
      }
    }
    Alert.alert(
      "Generate AI catalog photos?",
      `This will REPLACE both cover and gallery images with 5 AI photos of an Indian model wearing the garment, distributed across the ${aiStyles.length} selected style${aiStyles.length === 1 ? "" : "s"}. Your uploaded reference photo is kept SEPARATELY (not shown in the product gallery).\n\nThis takes 1-2 minutes — please keep the screen open.`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Generate", style: "default", onPress: () => runAIGeneration(ref) },
      ],
    );
  };

  const onRegenerateAI = async () => {
    if (!aiReference) {
      Alert.alert("No reference image", "Please upload a reference photo first using the Generate button.");
      return;
    }
    if (!subCategory) {
      Alert.alert("Pick a sub-category", "Please select Male, Female, Boys or Girls first.");
      return;
    }
    Alert.alert(
      "Regenerate AI photos?",
      `This will REPLACE the current cover + gallery with 5 fresh AI photos using the same reference image, distributed across the ${aiStyles.length} selected style${aiStyles.length === 1 ? "" : "s"}.`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Regenerate", style: "default", onPress: () => runAIGeneration(aiReference) },
      ],
    );
  };

  const onChangeReference = async () => {
    try {
      const data = await pickAndCompressImage({ aspect: [3, 4], width: 900 });
      if (data) {
        setAiReference(data);
        Alert.alert("Reference updated", "Tap Generate (or Regenerate) to create photos with this new reference.");
      }
    } catch (e) {
      Alert.alert("Image pick failed", formatApiError(e));
    }
  };

  const onSubmit = async () => {
    const priceN = Number(price);
    const stockN = Number(stock);
    if (!name.trim() || isNaN(priceN) || priceN < 0) {
      Alert.alert("Missing fields", "Name and a valid price are required.");
      return;
    }
    if (!imageUrl) {
      Alert.alert("Cover image required", "Please add a product cover image.");
      return;
    }
    // Device identity validation (July 2026) — blocks save on invalid IMEIs.
    if (imei1 && !isValidImei(imei1)) {
      Alert.alert("Invalid IMEI-1", "IMEI-1 must be 15 digits and pass the Luhn checksum. Dial *#06# on the device to see it exactly.");
      return;
    }
    if (imei2 && !isValidImei(imei2)) {
      Alert.alert("Invalid IMEI-2", "IMEI-2 must be 15 digits and pass the Luhn checksum.");
      return;
    }
    if (imei1 && imei2 && imei1 === imei2) {
      Alert.alert("Duplicate IMEIs", "IMEI-1 and IMEI-2 cannot be identical.");
      return;
    }
    setSaving(true);
    try {
      const extras: Record<string, string> = {};
      extraAttrs.forEach((e) => { if (e.key.trim()) extras[e.key.trim()] = e.value; });

      const payload: any = {
        name: name.trim(),
        price: priceN,
        image_url: imageUrl,
        description: description.trim(),
        stock: isNaN(stockN) ? 0 : stockN,
        category: category.trim() || undefined,
        brand: brand.trim(),
        sub_features: subFeatures.filter((s) => s.trim()),
        images: galleryImages,
        price_summary: priceSummary,
        protection_summary: protectionSummary,
        warranty_summary: warrantySummary,
        delivery_summary: deliverySummary,
        attrs_brand: attrsBrand.trim(),
        attrs_os: attrsOs.trim(),
        attrs_ram: attrsRam.trim(),
        attrs_cpu_model: attrsCpuModel.trim(),
        attrs_cpu_speed: attrsCpuSpeed.trim(),
        attrs_storage: attrsStorage.trim(),
        extra_attrs: extras,
        spec_tabs: specTabs
          .map((t) => ({ name: t.name.trim(), rows: t.rows.filter((r) => r.label.trim() || r.value.trim()) }))
          .filter((t) => t.name || t.rows.length),
        whats_in_box: whatsInBox.filter((b) => b.name.trim() || b.image_data_url),
        sub_category: (subCategory || "").trim() || undefined,
        clothing_size: isClothes ? (clothingSize || undefined) : undefined,
        // Device identity (July 2026) — trimmed, `undefined` when blank so
        // the backend keeps a null/empty value rather than a literal "".
        serial_number: serialNumber.trim() || undefined,
        imei_1: imei1.replace(/\s+/g, "") || undefined,
        imei_2: imei2.replace(/\s+/g, "") || undefined,
      };
      // UPDATE 1 — Only admin editor sends is_published. Vendor editor omits
      // it entirely so the server keeps its own decision (backend also strips
      // this field from vendor PATCH as a defense-in-depth check).
      if (!hidePublishedToggle) {
        payload.is_published = published;
      }
      if (existing?.id) {
        await api.patch(endpoints.update(existing.id), payload);
      } else {
        await api.post(endpoints.create, payload);
      }
      onSaved();
    } catch (e) {
      Alert.alert("Save failed", formatApiError(e));
    } finally { setSaving(false); }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView style={modalStyles.overlay} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={[modalStyles.sheet, { maxHeight: "94%" }]}>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <Text style={modalStyles.title}>{existing?.id ? "Edit product" : "New product"}</Text>
            <TouchableOpacity onPress={onClose} style={{ padding: 6 }}><Feather name="x" size={22} color={colors.textMain} /></TouchableOpacity>
          </View>

          <ScrollView keyboardShouldPersistTaps="handled" style={{ marginBottom: 12 }} contentContainerStyle={{ paddingBottom: 12 }}>

            {/* ── Section 1: Basics ── */}
            <Section
              title="Basics"
              icon="info"
              defaultOpen
              summary={name ? `${name} · ${price ? `₹${price}` : "no price"}` : "Name, price, stock, category"}
              testID="section-basics"
            >
              {/* UPDATE 2 — Smart product-master search. Only shown in the
                  vendor form (admin authors the master and doesn't need it). */}
              {showMasterSearch ? (
                <View style={sectionStyles.masterWrap} testID="master-search-wrap">
                  <View style={sectionStyles.masterHead}>
                    <Feather name="zap" size={14} color={colors.primary} />
                    <Text style={sectionStyles.masterTitle}>Smart search</Text>
                    <Text style={sectionStyles.masterSub}>tap a match to auto-fill everything</Text>
                  </View>
                  <View style={sectionStyles.masterInputRow}>
                    <Feather name="search" size={16} color={colors.textMuted} />
                    <TextInput
                      value={masterQuery}
                      onChangeText={setMasterQuery}
                      onFocus={() => { if (masterResults.length) setMasterOpen(true); }}
                      placeholder="e.g. iPhone 15, Realme 12 Pro, Samsung S24"
                      placeholderTextColor={colors.textMuted}
                      style={sectionStyles.masterInput}
                      testID="product-master-search"
                    />
                    {masterQuery.length > 0 ? (
                      <TouchableOpacity onPress={() => { setMasterQuery(""); setMasterResults([]); setMasterOpen(false); }} testID="product-master-clear">
                        <Feather name="x-circle" size={16} color={colors.textMuted} />
                      </TouchableOpacity>
                    ) : null}
                    {masterBusy ? <ActivityIndicator size="small" color={colors.primary} /> : null}
                  </View>

                  {/* Source filter chips — All / Slangcart / 91mobiles */}
                  {masterOpen && masterResults.length > 0 ? (
                    <View style={sectionStyles.masterChipsRow}>
                      {([
                        { key: "all", label: "All", icon: "layers" as const, count: masterResults.length },
                        { key: "local", label: "Slangcart", icon: "shopping-bag" as const, count: masterResults.filter((r: any) => r.source === "local").length },
                        { key: "91mobiles", label: "91mobiles", icon: "smartphone" as const, count: masterResults.filter((r: any) => r.source === "91mobiles").length },
                        { key: "deodap", label: "Deodap", icon: "package" as const, count: masterResults.filter((r: any) => r.source === "deodap").length },
                      ]).map((c) => {
                        const active = masterSource === c.key;
                        return (
                          <TouchableOpacity
                            key={c.key}
                            onPress={() => setMasterSource(c.key as any)}
                            style={[sectionStyles.masterChip, active && sectionStyles.masterChipActive]}
                            testID={`master-source-${c.key}`}
                          >
                            <Feather name={c.icon} size={11} color={active ? "#fff" : colors.primary} />
                            <Text style={[sectionStyles.masterChipText, active && sectionStyles.masterChipTextActive]}>{c.label}</Text>
                            <View style={[sectionStyles.masterChipCount, active && sectionStyles.masterChipCountActive]}>
                              <Text style={[sectionStyles.masterChipCountText, active && sectionStyles.masterChipCountTextActive]}>{c.count}</Text>
                            </View>
                          </TouchableOpacity>
                        );
                      })}
                    </View>
                  ) : null}

                  {masterOpen ? (
                    (() => {
                      const filtered = masterSource === "all"
                        ? masterResults
                        : masterResults.filter((r: any) => r.source === masterSource);
                      return filtered.length > 0 ? (
                      <View style={sectionStyles.masterDropdown}>
                        {filtered.map((row: any, i: number) => (
                          <TouchableOpacity
                            key={`m-${row.id || i}`}
                            onPress={() => applyMasterMatch(row)}
                            style={sectionStyles.masterRow}
                            activeOpacity={0.7}
                            testID={`product-master-row-${i}`}
                          >
                            {row.image_url ? (
                              <Image source={{ uri: row.image_url }} style={sectionStyles.masterImg} />
                            ) : (
                              <View style={[sectionStyles.masterImg, { backgroundColor: colors.surfaceMuted, alignItems: "center", justifyContent: "center" }]}>
                                <Feather name="image" size={14} color={colors.textMuted} />
                              </View>
                            )}
                            <View style={{ flex: 1 }}>
                              <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                                <Text style={sectionStyles.masterName} numberOfLines={2}>{row.name}</Text>
                                {row.source === "91mobiles" ? (
                                  <View style={sectionStyles.masterSrcBadge}>
                                    <Feather name="smartphone" size={9} color="#7C3AED" />
                                    <Text style={sectionStyles.masterSrcBadgeText}>91mobiles</Text>
                                  </View>
                                ) : row.source === "deodap" ? (
                                  <View style={sectionStyles.masterSrcBadgeDeodap}>
                                    <Feather name="package" size={9} color="#0F766E" />
                                    <Text style={sectionStyles.masterSrcBadgeDeodapText}>Deodap</Text>
                                  </View>
                                ) : null}
                              </View>
                              <Text style={sectionStyles.masterMeta} numberOfLines={1}>
                                {[row.brand, row.category].filter(Boolean).join(" · ") || "—"}
                              </Text>
                              {Array.isArray(row.sub_features) && row.sub_features.length ? (
                                <Text style={sectionStyles.masterSpecs} numberOfLines={1}>
                                  {row.sub_features.slice(0, 3).join(" · ")}
                                </Text>
                              ) : null}
                            </View>
                            <View style={{ alignItems: "flex-end" }}>
                              {row.price ? <Text style={sectionStyles.masterPrice}>₹{Math.round(row.price).toLocaleString("en-IN")}</Text> : null}
                              <Feather name="chevron-right" size={14} color={colors.primary} />
                            </View>
                          </TouchableOpacity>
                        ))}
                      </View>
                      ) : (
                        <View style={sectionStyles.masterEmpty}>
                          <Feather name="info" size={13} color={colors.textMuted} />
                          <Text style={sectionStyles.masterEmptyText}>
                            No {masterSource === "local" ? "Slangcart" : "91mobiles"} results for this query. Try another filter.
                          </Text>
                        </View>
                      );
                    })()
                  ) : null}
                  {masterOpen && masterResults.length === 0 && masterExternalHint ? (
                      <View style={sectionStyles.masterEmpty}>
                        <Feather name="info" size={13} color={colors.textMuted} />
                        <Text style={sectionStyles.masterEmptyText}>{masterExternalHint}</Text>
                      </View>
                  ) : null}
                </View>
              ) : null}

              <View style={{ flexDirection: "row", gap: 8 }}>
                <TouchableOpacity onPress={onPickCover} style={[modalStyles.imagePick, { flex: 1 }]} testID="product-image-pick">
                  {imageUrl ? <Image source={{ uri: imageUrl }} style={modalStyles.imagePickImg} /> : (
                    <View style={modalStyles.imagePickPlaceholder}>
                      {picking ? <ActivityIndicator color={colors.primary} /> : (
                        <>
                          <Feather name="image" size={24} color={colors.textMuted} />
                          <Text style={{ color: colors.textMuted, marginTop: 6, fontSize: 12 }}>Tap to pick cover image</Text>
                        </>
                      )}
                    </View>
                  )}
                </TouchableOpacity>
              </View>
              {/* Sept 2026 — Free image picker (Openverse + Wikimedia CC). */}
              <TouchableOpacity
                onPress={() => {
                  setImgPickerQuery(name || masterQuery || "");
                  setImgPickerResults([]);
                  setImgPickerErr("");
                  setImgPickerSelected(new Set());
                  setImgPickerOpen(true);
                }}
                style={sectionStyles.freeImgBtn}
                testID="free-image-picker-btn"
              >
                <Feather name="search" size={14} color={colors.primary} />
                <Text style={sectionStyles.freeImgBtnText}>Free image picker</Text>
                <Text style={sectionStyles.freeImgBtnHint}>Non-e-commerce · Creative Commons</Text>
              </TouchableOpacity>
              <Text style={modalStyles.fieldLabel}>Name</Text>
              <TextInput value={name} onChangeText={setName} style={modalStyles.input} testID="product-name" />
              <Text style={modalStyles.fieldLabel}>Price (₹)</Text>
              <TextInput value={price} onChangeText={setPrice} keyboardType="decimal-pad" style={modalStyles.input} testID="product-price" />
              <Text style={modalStyles.fieldLabel}>Stock</Text>
              <TextInput value={stock} onChangeText={setStock} keyboardType="number-pad" style={modalStyles.input} testID="product-stock" />
              <Text style={modalStyles.fieldLabel}>Category</Text>
              <View style={sectionStyles.chipRow}>
                {categoryChips.map((opt) => {
                  const selected = opt === "Other"
                    ? customCategory
                    : !customCategory && category === opt;
                  return (
                    <TouchableOpacity
                      key={opt}
                      onPress={() => {
                        if (opt === "Other") {
                          setCustomCategory(true);
                          // keep current text if present
                        } else {
                          setCustomCategory(false);
                          setCategory(opt);
                          // Reset clothes-only fields when switching away
                          if (opt.toLowerCase() !== "clothes") {
                            setSubCategory("");
                            setClothingSize("");
                          }
                        }
                      }}
                      style={[sectionStyles.chip, selected && sectionStyles.chipActive]}
                      testID={`product-category-${opt.toLowerCase()}`}
                    >
                      <Text style={[sectionStyles.chipText, selected && sectionStyles.chipTextActive]}>{opt}</Text>
                    </TouchableOpacity>
                  );
                })}
              </View>
              {customCategory ? (
                <TextInput
                  value={category}
                  onChangeText={setCategory}
                  placeholder="Type a custom category"
                  placeholderTextColor={colors.textMuted}
                  style={[modalStyles.input, { marginTop: 8 }]}
                  testID="product-category-custom"
                />
              ) : null}

              {/* Sept 2026 — Generic sub-category field for non-Clothes.
                  Powers the cascading sub-category chip strip on the
                  customer category screen (Mobiles → Accessories /
                  Chargers / Pendrive / Power bank etc.).  Clothes still
                  uses its own gender chip picker below.

                  Nov 2026 — When the picked parent category has admin-
                  managed subcategories, we render them as chips (source
                  of truth). Free-form text is still allowed for cases
                  where the admin tree isn't populated yet. */}
              {!isClothes && category ? (
                <>
                  <Text style={modalStyles.fieldLabel}>Sub-category (optional)</Text>
                  <Text style={{ fontSize: 11, color: colors.textMuted, marginBottom: 4 }}>
                    Groups products inside “{category}”.
                  </Text>
                  {subcategoryChips.length > 0 ? (
                    <View style={sectionStyles.chipRow}>
                      {subcategoryChips.map((sc) => {
                        const active = subCategory.trim().toLowerCase() === sc.toLowerCase();
                        return (
                          <TouchableOpacity
                            key={sc}
                            onPress={() => setSubCategory(active ? "" : sc)}
                            style={[sectionStyles.chip, active && sectionStyles.chipActive]}
                            testID={`product-subcat-${sc.toLowerCase()}`}
                          >
                            <Text style={[sectionStyles.chipText, active && sectionStyles.chipTextActive]}>{sc}</Text>
                          </TouchableOpacity>
                        );
                      })}
                    </View>
                  ) : null}
                  <TextInput
                    value={subCategory}
                    onChangeText={setSubCategory}
                    placeholder={subcategoryChips.length > 0 ? "Or type your own" : "e.g. Accessories"}
                    placeholderTextColor={colors.textMuted}
                    style={[modalStyles.input, subcategoryChips.length > 0 && { marginTop: 6 }]}
                    testID="product-subcat-generic"
                    maxLength={40}
                  />
                </>
              ) : null}

              {/* Clothes-specific sub-category + size */}
              {isClothes ? (
                <View style={sectionStyles.clothesBlock}>
                  <Text style={[modalStyles.fieldLabel, { marginTop: 0 }]}>Sub-category</Text>
                  <View style={sectionStyles.chipRow}>
                    {CLOTHES_SUB_OPTIONS.map((s) => (
                      <TouchableOpacity
                        key={s.key}
                        onPress={() => setSubCategory(s.key)}
                        style={[sectionStyles.chip, subCategory === s.key && sectionStyles.chipActive]}
                        testID={`product-subcat-${s.key}`}
                      >
                        <Text style={[sectionStyles.chipText, subCategory === s.key && sectionStyles.chipTextActive]}>{s.label}</Text>
                      </TouchableOpacity>
                    ))}
                  </View>                  <Text style={modalStyles.fieldLabel}>Size</Text>
                  <View style={sectionStyles.chipRow}>
                    {CLOTHES_SIZE_OPTIONS.map((sz) => (
                      <TouchableOpacity
                        key={sz}
                        onPress={() => setClothingSize(clothingSize === sz ? "" : sz)}
                        style={[sectionStyles.chip, clothingSize === sz && sectionStyles.chipActive, { minWidth: 50 }]}
                        testID={`product-size-${sz}`}
                      >
                        <Text style={[sectionStyles.chipText, clothingSize === sz && sectionStyles.chipTextActive]}>{sz}</Text>
                      </TouchableOpacity>
                    ))}
                  </View>

                  {/* ── AI image generator — ADMIN ONLY.
                       Vendors must upload product photos manually (the regular
                       cover + gallery upload above). This is intentional: the
                       app shares one Emergent LLM Key budget across all users,
                       and unrestricted vendor AI access would drain it
                       instantly. To enable AI per-vendor in the future, add a
                       paid credit wallet and re-enable this block. ── */}
                  {canUseAI ? (
                    <>
                      <Text style={modalStyles.fieldLabel}>AI photo styles</Text>
                  <View style={sectionStyles.chipRow}>
                    {AI_STYLES.map((s) => {
                      const active = aiStyles.includes(s.key);
                      return (
                        <TouchableOpacity
                          key={s.key}
                          onPress={() => toggleStyle(s.key)}
                          style={[sectionStyles.chip, active && sectionStyles.chipActive]}
                          testID={`product-ai-style-${s.key}`}
                        >
                          <Text style={[sectionStyles.chipText, active && sectionStyles.chipTextActive]}>{s.label}</Text>
                        </TouchableOpacity>
                      );
                    })}
                  </View>
                  <Text style={[sectionStyles.aiHint, { marginTop: 4 }]}>
                    Pick one or more styles. 5 images will be split across them automatically
                    (1→5, 2→3+2, 3→2+2+1, 4→2+1+1+1, 5→1 each).
                  </Text>

                  {/* ── Reference image preview (kept SEPARATE from cover/gallery) ── */}
                  {aiReference ? (
                    <View style={sectionStyles.aiRefRow}>
                      <Image source={{ uri: aiReference }} style={sectionStyles.aiRefThumb} resizeMode="cover" />
                      <View style={{ flex: 1 }}>
                        <Text style={sectionStyles.aiRefLabel}>AI Reference</Text>
                        <Text style={sectionStyles.aiRefSub}>Used only as a guide — won't appear in the product gallery.</Text>
                      </View>
                      <TouchableOpacity onPress={onChangeReference} style={sectionStyles.aiRefBtn} testID="product-ai-ref-change">
                        <Feather name="refresh-cw" size={14} color={colors.primary} />
                        <Text style={sectionStyles.aiRefBtnText}>Change</Text>
                      </TouchableOpacity>
                    </View>
                  ) : null}

                  {/* AI Image Generator + Regenerate */}
                  <TouchableOpacity
                    onPress={onGenerateAI}
                    disabled={aiBusy}
                    style={[sectionStyles.aiBtn, aiBusy && { opacity: 0.7 }]}
                    testID="product-ai-generate"
                  >
                    {aiBusy ? (
                      <>
                        <ActivityIndicator color="#fff" />
                        <Text style={sectionStyles.aiBtnText}>
                          {aiProgress ? `Generating ${aiProgress.done}/${aiProgress.total}…` : "Generating AI photos…"}
                        </Text>
                      </>
                    ) : (
                      <>
                        <Feather name="zap" size={16} color="#fff" />
                        <Text style={sectionStyles.aiBtnText}>
                          {aiReference ? "Generate 5 AI Photos" : "Pick reference & Generate"}
                        </Text>
                      </>
                    )}
                  </TouchableOpacity>
                  {aiProduced && aiReference ? (
                    <TouchableOpacity
                      onPress={onRegenerateAI}
                      disabled={aiBusy}
                      style={[sectionStyles.aiBtnSecondary, aiBusy && { opacity: 0.7 }]}
                      testID="product-ai-regenerate"
                    >
                      <Feather name="refresh-cw" size={14} color={colors.primary} />
                      <Text style={sectionStyles.aiBtnSecondaryText}>Regenerate (Realign)</Text>
                    </TouchableOpacity>
                  ) : null}
                  <Text style={sectionStyles.aiHint}>
                    AI replaces both cover and gallery with 5 photorealistic Indian model photos.
                    Each photo takes ~25s. The reference image is kept separately and never shown
                    to customers.
                  </Text>
                    </>
                  ) : null}
                </View>
              ) : null}

              <Text style={modalStyles.fieldLabel}>Description</Text>
              <TextInput value={description} onChangeText={setDescription} multiline style={[modalStyles.input, { minHeight: 70, paddingTop: 12 }]} testID="product-description" />
              {hidePublishedToggle ? (
                <View style={modalStyles.publishNotice}>
                  <Feather name="shield" size={14} color={colors.primary} />
                  <Text style={modalStyles.publishNoticeText}>
                    Your product is submitted for admin review. It becomes visible in the Shop once an admin approves it.
                  </Text>
                </View>
              ) : (
                <View style={modalStyles.switchRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={modalStyles.switchTitle}>Published</Text>
                    <Text style={modalStyles.switchSub}>Hidden products are not shown to users in the shop.</Text>
                  </View>
                  <Switch value={published} onValueChange={setPublished} testID="product-published" />
                </View>
              )}
            </Section>

            {/* ── Section 1b: Device Identity (Serial / IMEI-1 / IMEI-2) ── */}
            {/* Optional across ALL products so single-unit vendors (phone
                shops especially) can track exact stock.  IMEIs are validated
                with the Luhn checksum client-side; the backend just stores. */}
            <Section
              title="Device Identity"
              icon="hash"
              summary={
                [
                  serialNumber && `SN ${serialNumber.slice(0, 8)}${serialNumber.length > 8 ? "…" : ""}`,
                  imei1 && `IMEI-1 ${imei1.slice(0, 6)}…`,
                  imei2 && `IMEI-2 ${imei2.slice(0, 6)}…`,
                ].filter(Boolean).join(" · ") || "Serial number • IMEI-1 • IMEI-2 (optional)"
              }
              testID="section-device-id"
            >
              <Text style={{ fontSize: 11, color: colors.textMuted, marginBottom: 8 }}>
                Optional. For phones / branded electronics tracked per unit. IMEIs must be exactly 15 digits and pass the Luhn checksum.
              </Text>

              <Text style={modalStyles.fieldLabel}>Serial number</Text>
              <View style={sectionStyles.scanRow}>
                <TextInput
                  value={serialNumber}
                  onChangeText={setSerialNumber}
                  placeholder="e.g. SN-2024-A12345678"
                  placeholderTextColor={colors.textMuted}
                  style={[modalStyles.input, { flex: 1 }]}
                  autoCapitalize="characters"
                  testID="product-serial"
                />
                <TouchableOpacity onPress={() => setScannerTarget("serial")} style={sectionStyles.scanBtn} testID="product-serial-scan">
                  <Feather name="camera" size={16} color={colors.primary} />
                </TouchableOpacity>
              </View>

              <Text style={[modalStyles.fieldLabel, { marginTop: 12 }]}>IMEI-1</Text>
              <View style={sectionStyles.scanRow}>
                <TextInput
                  value={imei1}
                  onChangeText={(t) => setImei1(t.replace(/[^\d]/g, "").slice(0, 15))}
                  placeholder="15-digit IMEI (dial *#06#)"
                  placeholderTextColor={colors.textMuted}
                  keyboardType="number-pad"
                  maxLength={15}
                  style={[
                    modalStyles.input,
                    { flex: 1 },
                    imei1.length > 0 && !isValidImei(imei1) && sectionStyles.inputError,
                  ]}
                  testID="product-imei-1"
                />
                <TouchableOpacity onPress={() => setScannerTarget("imei_1")} style={sectionStyles.scanBtn} testID="product-imei-1-scan">
                  <Feather name="camera" size={16} color={colors.primary} />
                </TouchableOpacity>
              </View>
              {imei1.length > 0 ? (
                <View style={sectionStyles.imeiHintRow}>
                  {isValidImei(imei1) ? (
                    <>
                      <Feather name="check-circle" size={12} color="#0F9D58" />
                      <Text style={[sectionStyles.imeiHintText, { color: "#0F9D58" }]}>Valid IMEI ({imei1.length}/15)</Text>
                    </>
                  ) : (
                    <>
                      <Feather name="alert-triangle" size={12} color="#B3261E" />
                      <Text style={[sectionStyles.imeiHintText, { color: "#B3261E" }]}>
                        {imei1.length < 15 ? `${imei1.length}/15 digits` : "Failed Luhn checksum — please re-check"}
                      </Text>
                    </>
                  )}
                </View>
              ) : null}

              <Text style={[modalStyles.fieldLabel, { marginTop: 12 }]}>IMEI-2 (dual-SIM devices)</Text>
              <View style={sectionStyles.scanRow}>
                <TextInput
                  value={imei2}
                  onChangeText={(t) => setImei2(t.replace(/[^\d]/g, "").slice(0, 15))}
                  placeholder="Second 15-digit IMEI (if applicable)"
                  placeholderTextColor={colors.textMuted}
                  keyboardType="number-pad"
                  maxLength={15}
                  style={[
                    modalStyles.input,
                    { flex: 1 },
                    imei2.length > 0 && !isValidImei(imei2) && sectionStyles.inputError,
                  ]}
                  testID="product-imei-2"
                />
                <TouchableOpacity onPress={() => setScannerTarget("imei_2")} style={sectionStyles.scanBtn} testID="product-imei-2-scan">
                  <Feather name="camera" size={16} color={colors.primary} />
                </TouchableOpacity>
              </View>
              {imei2.length > 0 ? (
                <View style={sectionStyles.imeiHintRow}>
                  {isValidImei(imei2) ? (
                    <>
                      <Feather name="check-circle" size={12} color="#0F9D58" />
                      <Text style={[sectionStyles.imeiHintText, { color: "#0F9D58" }]}>Valid IMEI ({imei2.length}/15)</Text>
                    </>
                  ) : (
                    <>
                      <Feather name="alert-triangle" size={12} color="#B3261E" />
                      <Text style={[sectionStyles.imeiHintText, { color: "#B3261E" }]}>
                        {imei2.length < 15 ? `${imei2.length}/15 digits` : "Failed Luhn checksum — please re-check"}
                      </Text>
                    </>
                  )}
                </View>
              ) : null}

              {imei1 && imei2 && imei1 === imei2 ? (
                <View style={sectionStyles.imeiHintRow}>
                  <Feather name="alert-triangle" size={12} color="#B3261E" />
                  <Text style={[sectionStyles.imeiHintText, { color: "#B3261E" }]}>
                    IMEI-1 and IMEI-2 cannot be identical.
                  </Text>
                </View>
              ) : null}
            </Section>

            {/* ── Section 2: Brand & Sub-features ── */}
            <Section
              title="Brand & Sub-features"
              icon="tag"
              summary={brand ? `${brand} · ${subFeatures.length} feature${subFeatures.length === 1 ? "" : "s"}` : "Bullet list under product name"}
              testID="section-brand"
            >
              <Text style={modalStyles.fieldLabel}>Brand name</Text>
              <TextInput value={brand} onChangeText={setBrand} placeholder="e.g. Apple, Samsung" placeholderTextColor={colors.textMuted} style={modalStyles.input} testID="product-brand" />
              <Text style={modalStyles.fieldLabel}>Sub-features (bullet points)</Text>
              {subFeatures.map((f, i) => (
                <View key={i} style={sectionStyles.row}>
                  <Feather name="check-circle" size={14} color={colors.primary} />
                  <Text style={sectionStyles.rowText} numberOfLines={2}>{f}</Text>
                  <TouchableOpacity onPress={() => setSubFeatures(subFeatures.filter((_, j) => j !== i))}>
                    <Feather name="x" size={16} color="#B3261E" />
                  </TouchableOpacity>
                </View>
              ))}
              <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
                <TextInput
                  value={newSubFeature}
                  onChangeText={setNewSubFeature}
                  placeholder="Type a feature and tap +"
                  placeholderTextColor={colors.textMuted}
                  style={[modalStyles.input, { flex: 1 }]}
                  onSubmitEditing={onAddSubFeature}
                  testID="product-sub-feature-input"
                />
                <TouchableOpacity onPress={onAddSubFeature} style={sectionStyles.addBtn} testID="product-sub-feature-add">
                  <Feather name="plus" size={18} color={colors.primaryFg} />
                </TouchableOpacity>
              </View>
            </Section>

            {/* ── Section 3: Gallery ── */}
            <Section
              title="Gallery (up to 10)"
              icon="image"
              summary={`${galleryImages.length}/10 image${galleryImages.length === 1 ? "" : "s"}`}
              testID="section-gallery"
            >
              <Text style={{ fontSize: 11, color: colors.textMuted, marginBottom: 8 }}>
                The cover image (above) is shown first. Add up to 10 additional images for the product gallery.
              </Text>
              <View style={sectionStyles.galleryGrid}>
                {galleryImages.map((img, i) => (
                  <View key={i} style={sectionStyles.galleryItem}>
                    <Image source={{ uri: img }} style={sectionStyles.galleryImg} />
                    <TouchableOpacity
                      onPress={() => setGalleryImages(galleryImages.filter((_, j) => j !== i))}
                      style={sectionStyles.galleryRemove}
                    >
                      <Feather name="x" size={12} color="#fff" />
                    </TouchableOpacity>
                  </View>
                ))}
                {galleryImages.length < 10 && (
                  <TouchableOpacity onPress={onAddGalleryImage} style={sectionStyles.galleryAdd} testID="product-gallery-add">
                    <Feather name="plus" size={20} color={colors.primary} />
                    <Text style={{ fontSize: 10, color: colors.primary, fontWeight: "700", marginTop: 2 }}>Add</Text>
                  </TouchableOpacity>
                )}
              </View>
            </Section>

            {/* ── Section 4: Styled Summaries ── */}
            <Section
              title="Styled Summaries"
              icon="layout"
              summary="Price · Protection · Warranty · Delivery"
              testID="section-summaries"
            >
              <Text style={modalStyles.fieldLabel}>Price summary</Text>
              <StyledTextEditor value={priceSummary} onChange={setPriceSummary} placeholder="e.g. ₹1,499 inclusive of all taxes (Free shipping)" testID="product-price-summary" />
              <Text style={modalStyles.fieldLabel}>Protection summary</Text>
              <StyledTextEditor value={protectionSummary} onChange={setProtectionSummary} placeholder="e.g. 1-year manufacturer warranty + 2-year extended at checkout" testID="product-protection-summary" />
              <Text style={modalStyles.fieldLabel}>Warranty summary</Text>
              <StyledTextEditor value={warrantySummary} onChange={setWarrantySummary} placeholder="e.g. Free replacement within 7 days of delivery" testID="product-warranty-summary" />
              <Text style={modalStyles.fieldLabel}>Delivery summary</Text>
              <StyledTextEditor value={deliverySummary} onChange={setDeliverySummary} placeholder="e.g. Free delivery in 2-4 business days" testID="product-delivery-summary" />
            </Section>

            {/* ── Section 5: Key Attributes ── */}
            <Section
              title="Key Attributes"
              icon="sliders"
              summary="Brand · OS · RAM · CPU · Storage + extras"
              testID="section-attrs"
            >
              <Text style={modalStyles.fieldLabel}>Brand</Text>
              <TextInput value={attrsBrand} onChangeText={setAttrsBrand} placeholder="e.g. Samsung" placeholderTextColor={colors.textMuted} style={modalStyles.input} />
              <Text style={modalStyles.fieldLabel}>OS</Text>
              <TextInput value={attrsOs} onChangeText={setAttrsOs} placeholder="e.g. Android 14" placeholderTextColor={colors.textMuted} style={modalStyles.input} />
              <Text style={modalStyles.fieldLabel}>RAM</Text>
              <TextInput value={attrsRam} onChangeText={setAttrsRam} placeholder="e.g. 8 GB" placeholderTextColor={colors.textMuted} style={modalStyles.input} />
              <Text style={modalStyles.fieldLabel}>CPU model</Text>
              <TextInput value={attrsCpuModel} onChangeText={setAttrsCpuModel} placeholder="e.g. Snapdragon 8 Gen 3" placeholderTextColor={colors.textMuted} style={modalStyles.input} />
              <Text style={modalStyles.fieldLabel}>CPU speed</Text>
              <TextInput value={attrsCpuSpeed} onChangeText={setAttrsCpuSpeed} placeholder="e.g. 3.3 GHz" placeholderTextColor={colors.textMuted} style={modalStyles.input} />
              <Text style={modalStyles.fieldLabel}>Storage</Text>
              <TextInput value={attrsStorage} onChangeText={setAttrsStorage} placeholder="e.g. 256 GB" placeholderTextColor={colors.textMuted} style={modalStyles.input} />

              <Text style={[modalStyles.fieldLabel, { marginTop: 16 }]}>Extra attributes</Text>
              {extraAttrs.map((kv, i) => (
                <View key={i} style={{ flexDirection: "row", gap: 6, marginBottom: 6 }}>
                  <TextInput
                    value={kv.key}
                    onChangeText={(t) => { const n = [...extraAttrs]; n[i] = { ...n[i], key: t }; setExtraAttrs(n); }}
                    placeholder="Label"
                    placeholderTextColor={colors.textMuted}
                    style={[modalStyles.input, { flex: 1 }]}
                  />
                  <TextInput
                    value={kv.value}
                    onChangeText={(t) => { const n = [...extraAttrs]; n[i] = { ...n[i], value: t }; setExtraAttrs(n); }}
                    placeholder="Value"
                    placeholderTextColor={colors.textMuted}
                    style={[modalStyles.input, { flex: 1.4 }]}
                  />
                  <TouchableOpacity onPress={() => setExtraAttrs(extraAttrs.filter((_, j) => j !== i))} style={sectionStyles.smallDangerBtn}>
                    <Feather name="trash-2" size={14} color="#B3261E" />
                  </TouchableOpacity>
                </View>
              ))}
              <TouchableOpacity onPress={onAddExtraAttr} style={sectionStyles.outlineBtn} testID="product-extra-attr-add">
                <Feather name="plus" size={14} color={colors.primary} />
                <Text style={sectionStyles.outlineBtnText}>Add custom attribute</Text>
              </TouchableOpacity>
            </Section>

            {/* ── Section 6: Specification Tabs ── */}
            <Section
              title="Specification Tabs"
              icon="grid"
              summary={`${specTabs.length} tab${specTabs.length === 1 ? "" : "s"}`}
              testID="section-specs"
            >
              <Text style={{ fontSize: 11, color: colors.textMuted, marginBottom: 8 }}>
                Group specs into tabs (General, Display, Battery, etc). Each tab holds label/value rows.
              </Text>
              {/* UPDATE 2c — One-tap load of the 91mobiles-style spec skeleton
                  so vendor listings match the detail-page structure buyers
                  see there.  Merges by default so existing tabs are kept. */}
              <View style={sectionStyles.tplRow}>
                <TouchableOpacity onPress={() => loadM91Template("merge")} style={sectionStyles.tplBtn} testID="product-spec-tpl-merge">
                  <Feather name="download" size={13} color={colors.primary} />
                  <Text style={sectionStyles.tplBtnText}>Load 91mobiles template</Text>
                </TouchableOpacity>
                {specTabs.length > 0 ? (
                  <TouchableOpacity onPress={() => loadM91Template("replace")} style={[sectionStyles.tplBtn, sectionStyles.tplBtnGhost]} testID="product-spec-tpl-replace">
                    <Feather name="refresh-cw" size={12} color={colors.textMuted} />
                    <Text style={[sectionStyles.tplBtnText, { color: colors.textMuted }]}>Replace</Text>
                  </TouchableOpacity>
                ) : null}
              </View>
              {/* UPDATE 3 (August 2026) — Empty-state banner surfaces when the
                  backend can't find the phone on GSMArena so the vendor
                  knows they'll need to fill values manually. */}
              {specsNotFoundHint ? (
                <View style={sectionStyles.notFoundBanner} testID="specs-not-found-hint">
                  <Feather name="alert-circle" size={14} color="#B37500" />
                  <Text style={sectionStyles.notFoundText}>{specsNotFoundHint}</Text>
                  <TouchableOpacity onPress={() => setSpecsNotFoundHint("")} testID="specs-not-found-close">
                    <Feather name="x" size={14} color="#B37500" />
                  </TouchableOpacity>
                </View>
              ) : null}
              {specTabs.map((tab, ti) => (
                <View key={ti} style={sectionStyles.specTabCard}>
                  <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
                    <TextInput
                      value={tab.name}
                      onChangeText={(t) => { const n = [...specTabs]; n[ti] = { ...n[ti], name: t }; setSpecTabs(n); }}
                      placeholder="Tab name (e.g. Display)"
                      placeholderTextColor={colors.textMuted}
                      style={[modalStyles.input, { flex: 1 }]}
                    />
                    <TouchableOpacity onPress={() => setSpecTabs(specTabs.filter((_, j) => j !== ti))} style={sectionStyles.smallDangerBtn}>
                      <Feather name="trash-2" size={14} color="#B3261E" />
                    </TouchableOpacity>
                  </View>
                  {tab.rows.map((row, ri) => (
                    <View key={ri} style={{ flexDirection: "row", gap: 6, marginTop: 8 }}>
                      <TextInput
                        value={row.label}
                        onChangeText={(t) => { const n = [...specTabs]; n[ti].rows[ri] = { ...row, label: t }; setSpecTabs(n); }}
                        placeholder="Label"
                        placeholderTextColor={colors.textMuted}
                        style={[modalStyles.input, { flex: 1 }]}
                      />
                      <TextInput
                        value={row.value}
                        onChangeText={(t) => { const n = [...specTabs]; n[ti].rows[ri] = { ...row, value: t }; setSpecTabs(n); }}
                        placeholder="Value"
                        placeholderTextColor={colors.textMuted}
                        style={[modalStyles.input, { flex: 1.4 }]}
                      />
                      <TouchableOpacity
                        onPress={() => { const n = [...specTabs]; n[ti] = { ...n[ti], rows: n[ti].rows.filter((_, k) => k !== ri) }; setSpecTabs(n); }}
                        style={sectionStyles.smallDangerBtn}
                      >
                        <Feather name="x" size={14} color="#B3261E" />
                      </TouchableOpacity>
                    </View>
                  ))}
                  <TouchableOpacity onPress={() => onAddSpecRow(ti)} style={[sectionStyles.outlineBtn, { marginTop: 8 }]}>
                    <Feather name="plus" size={14} color={colors.primary} />
                    <Text style={sectionStyles.outlineBtnText}>Add row</Text>
                  </TouchableOpacity>
                </View>
              ))}
              <TouchableOpacity onPress={onAddSpecTab} style={[sectionStyles.outlineBtn, { marginTop: 8 }]} testID="product-spec-tab-add">
                <Feather name="plus" size={14} color={colors.primary} />
                <Text style={sectionStyles.outlineBtnText}>Add spec tab</Text>
              </TouchableOpacity>
            </Section>

            {/* ── Section 7: What's in the Box ── */}
            <Section
              title="What's in the Box"
              icon="package"
              summary={`${whatsInBox.length} item${whatsInBox.length === 1 ? "" : "s"}`}
              testID="section-box"
            >
              <Text style={{ fontSize: 11, color: colors.textMuted, marginBottom: 8 }}>
                Items included in the package, with an optional thumbnail each.
              </Text>
              {whatsInBox.map((b, i) => (
                <View key={i} style={sectionStyles.boxItemRow}>
                  {b.image_data_url ? (
                    <Image source={{ uri: b.image_data_url }} style={sectionStyles.boxThumb} />
                  ) : (
                    <View style={[sectionStyles.boxThumb, { alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceMuted }]}>
                      <Feather name="image" size={14} color={colors.textMuted} />
                    </View>
                  )}
                  <TextInput
                    value={b.name}
                    onChangeText={(t) => { const n = [...whatsInBox]; n[i] = { ...n[i], name: t }; setWhatsInBox(n); }}
                    placeholder="Item name (e.g. Charging cable)"
                    placeholderTextColor={colors.textMuted}
                    style={[modalStyles.input, { flex: 1 }]}
                  />
                  <TouchableOpacity onPress={() => setWhatsInBox(whatsInBox.filter((_, j) => j !== i))} style={sectionStyles.smallDangerBtn}>
                    <Feather name="trash-2" size={14} color="#B3261E" />
                  </TouchableOpacity>
                </View>
              ))}
              <TouchableOpacity onPress={onAddBoxItem} style={[sectionStyles.outlineBtn, { marginTop: 8 }]} testID="product-box-add">
                <Feather name="plus" size={14} color={colors.primary} />
                <Text style={sectionStyles.outlineBtnText}>Add item</Text>
              </TouchableOpacity>
            </Section>
          </ScrollView>

          <View style={{ flexDirection: "row", gap: 10 }}>
            <TouchableOpacity onPress={onClose} style={[modalStyles.btn, { backgroundColor: colors.surfaceMuted }]}>
              <Text style={{ color: colors.textMain, fontWeight: "700" }}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={onSubmit} disabled={saving} style={[modalStyles.btn, { backgroundColor: colors.primary }, saving && { opacity: 0.6 }]} testID="product-save">
              {saving ? <ActivityIndicator color={colors.primaryFg} /> : (
                <Text style={{ color: colors.primaryFg, fontWeight: "800" }}>{existing?.id ? "Save changes" : "Create product"}</Text>
              )}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
      {/* UPDATE 3 — Barcode scanner overlay. Rendered as sibling so it
          floats above the RichProductEditor modal. */}
      <BarcodeScannerModal
        visible={scannerTarget !== null}
        target={scannerTarget || "serial"}
        onClose={() => setScannerTarget(null)}
        onScanned={(value) => {
          if (scannerTarget === "serial") setSerialNumber(value);
          else if (scannerTarget === "imei_1") setImei1(value.replace(/\D/g, "").slice(0, 15));
          else if (scannerTarget === "imei_2") setImei2(value.replace(/\D/g, "").slice(0, 15));
          setScannerTarget(null);
        }}
      />

      {/* Sept 2026 — Free image picker modal (Openverse + Wikimedia CC).
          Sibling to the main product Modal so it floats above it. */}
      <Modal visible={imgPickerOpen} animationType="slide" onRequestClose={() => setImgPickerOpen(false)} transparent>
        <View style={modalStyles.overlay}>
          <View style={[modalStyles.sheet, { maxHeight: "92%", padding: 18 }]}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 10 }}>
              <Feather name="image" size={18} color={colors.primary} />
              <Text style={[modalStyles.title, { marginBottom: 0, flex: 1 }]}>Free image picker</Text>
              <TouchableOpacity onPress={() => setImgPickerOpen(false)} testID="free-img-close">
                <Feather name="x" size={22} color={colors.textMain} />
              </TouchableOpacity>
            </View>
            <Text style={{ fontSize: 11, color: colors.textMuted, marginBottom: 8 }}>
              Non-e-commerce, royalty-free (Creative Commons). Auto-translates Bellam→Jaggery, Uddi/Minap pappu→Urad dal, Kandi pappu→Toor dal, Senaga pappu→Chana dal, etc.
            </Text>

            <View style={{ flexDirection: "row", gap: 6 }}>
              <TextInput
                value={imgPickerQuery}
                onChangeText={setImgPickerQuery}
                onSubmitEditing={() => runFreeImageSearch()}
                placeholder="e.g. sugar, jaggery, urad dal"
                placeholderTextColor={colors.textMuted}
                returnKeyType="search"
                style={[modalStyles.input, { flex: 1 }]}
                testID="free-img-query"
              />
              <TouchableOpacity
                onPress={() => runFreeImageSearch()}
                disabled={imgPickerBusy || !imgPickerQuery.trim()}
                style={[sectionStyles.freeImgSearchBtn, (imgPickerBusy || !imgPickerQuery.trim()) && { opacity: 0.5 }]}
                testID="free-img-search"
              >
                {imgPickerBusy
                  ? <ActivityIndicator color="#fff" />
                  : <Feather name="search" size={16} color="#fff" />}
              </TouchableOpacity>
            </View>

            {imgPickerResolvedQuery && imgPickerResolvedQuery.toLowerCase() !== imgPickerQuery.trim().toLowerCase() ? (
              <Text style={{ fontSize: 11, color: colors.primary, marginTop: 6, fontWeight: "700" }}>
                Showing results for “{imgPickerResolvedQuery}” · translated from “{imgPickerQuery.trim()}”
              </Text>
            ) : null}
            {imgPickerErr ? (
              <View style={sectionStyles.freeImgError}>
                <Feather name="alert-circle" size={13} color="#B91C1C" />
                <Text style={{ fontSize: 12, color: "#B91C1C", flex: 1 }}>{imgPickerErr}</Text>
              </View>
            ) : null}

            {imgPickerBusy && imgPickerResults.length === 0 ? (
              <View style={{ padding: 30, alignItems: "center" }}>
                <ActivityIndicator color={colors.primary} />
                <Text style={{ fontSize: 12, color: colors.textMuted, marginTop: 6 }}>Searching Creative Commons…</Text>
              </View>
            ) : (
              <ScrollView style={{ marginTop: 10, maxHeight: 480 }} contentContainerStyle={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                {imgPickerResults.map((row) => {
                  const isSel = imgPickerSelected.has(row.image);
                  return (
                    <TouchableOpacity
                      key={row.image}
                      onPress={() => {
                        setImgPickerSelected((prev) => {
                          const nxt = new Set(prev);
                          if (nxt.has(row.image)) nxt.delete(row.image); else nxt.add(row.image);
                          return nxt;
                        });
                      }}
                      style={[sectionStyles.freeImgCell, isSel && sectionStyles.freeImgCellSel]}
                      testID={`free-img-cell-${row.image.slice(-20)}`}
                    >
                      <Image source={{ uri: proxiedImageUrl(row.thumbnail || row.image) }} style={sectionStyles.freeImgCellImg} />
                      {isSel ? (
                        <View style={sectionStyles.freeImgCellCheck}>
                          <Feather name="check" size={14} color="#fff" />
                        </View>
                      ) : null}
                      <View style={sectionStyles.freeImgCellFooter}>
                        <Text style={sectionStyles.freeImgCellSrc} numberOfLines={1}>{row.provider}</Text>
                      </View>
                    </TouchableOpacity>
                  );
                })}
              </ScrollView>
            )}

            {imgPickerResults.length > 0 ? (
              <View style={{ flexDirection: "row", gap: 8, marginTop: 12, alignItems: "center" }}>
                <Text style={{ fontSize: 12, color: colors.textMuted, flex: 1 }}>
                  {imgPickerSelected.size} of {imgPickerResults.length} selected
                </Text>
                <TouchableOpacity
                  onPress={applyImagePickerSelection}
                  disabled={imgPickerSelected.size === 0 || imgPickerBusy}
                  style={[sectionStyles.freeImgApplyBtn, (imgPickerSelected.size === 0 || imgPickerBusy) && { opacity: 0.5 }]}
                  testID="free-img-apply"
                >
                  {imgPickerBusy
                    ? <ActivityIndicator size="small" color="#fff" />
                    : (
                      <>
                        <Feather name="check" size={14} color="#fff" />
                        <Text style={{ color: "#fff", fontWeight: "800", fontSize: 12 }}>Use selected</Text>
                      </>
                    )}
                </TouchableOpacity>
              </View>
            ) : null}
          </View>
        </View>
      </Modal>
    </Modal>
  );
}

const modalStyles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.5)", justifyContent: "flex-end" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 24, paddingBottom: 40 },
  title: { fontSize: 20, fontWeight: "800", color: colors.textMain, marginBottom: 14 },
  fieldLabel: { fontSize: 12, color: colors.textMuted, fontWeight: "600", marginTop: 12, marginBottom: 6 },
  input: { backgroundColor: colors.surfaceMuted, borderRadius: radii.input, padding: 14, fontSize: 14, color: colors.textMain },
  imagePick: { height: 160, borderRadius: 16, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceMuted, overflow: "hidden", alignItems: "center", justifyContent: "center" },
  imagePickImg: { width: "100%", height: "100%" },
  imagePickPlaceholder: { alignItems: "center", justifyContent: "center" },
  switchRow: { flexDirection: "row", alignItems: "center", gap: 12, marginTop: 16, paddingVertical: 12, paddingHorizontal: 14, borderRadius: 12, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  switchTitle: { fontSize: 13, fontWeight: "700", color: colors.textMain },
  switchSub: { fontSize: 11, color: colors.textMuted, marginTop: 4 },
  publishNotice: {
    flexDirection: "row", alignItems: "flex-start", gap: 10, marginTop: 16,
    paddingVertical: 12, paddingHorizontal: 14, borderRadius: 12,
    borderWidth: 1, borderColor: colors.primary + "40",
    backgroundColor: colors.primary + "10",
  },
  publishNoticeText: { flex: 1, fontSize: 12, color: colors.textMain, lineHeight: 17, fontWeight: "600" },
  btn: { flex: 1, paddingVertical: 14, borderRadius: radii.button, alignItems: "center" },
});

const sectionStyles = StyleSheet.create({
  wrap: { marginBottom: 10, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, overflow: "hidden" },
  head: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14 },
  headIcon: { width: 32, height: 32, borderRadius: 10, backgroundColor: colors.primary + "12", alignItems: "center", justifyContent: "center" },
  headTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain, letterSpacing: -0.2 },
  headSummary: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  body: { paddingHorizontal: 14, paddingBottom: 14, paddingTop: 4 },
  // Sept 2026 — Free image picker (Openverse + Wikimedia CC).
  freeImgBtn: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 8, paddingHorizontal: 14, paddingVertical: 10, borderRadius: 12, borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.primary + "08" },
  freeImgBtnText: { fontSize: 12, fontWeight: "800", color: colors.primary, letterSpacing: 0.2 },
  freeImgBtnHint: { fontSize: 10, color: colors.textMuted, marginLeft: "auto" },
  freeImgSearchBtn: { width: 48, borderRadius: 12, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  freeImgError: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8, padding: 8, borderRadius: 8, backgroundColor: "#FEE2E2", borderWidth: 1, borderColor: "#FCA5A5" },
  freeImgCell: { width: "31%", aspectRatio: 1, borderRadius: 10, overflow: "hidden", backgroundColor: colors.surfaceMuted, borderWidth: 2, borderColor: "transparent", position: "relative" },
  freeImgCellSel: { borderColor: colors.primary },
  freeImgCellImg: { width: "100%", height: "100%", resizeMode: "cover" },
  freeImgCellCheck: { position: "absolute", top: 4, right: 4, width: 22, height: 22, borderRadius: 11, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },
  freeImgCellFooter: { position: "absolute", bottom: 0, left: 0, right: 0, backgroundColor: "rgba(0,0,0,0.55)", paddingHorizontal: 6, paddingVertical: 3 },
  freeImgCellSrc: { fontSize: 9, color: "#fff", fontWeight: "700", letterSpacing: 0.3, textTransform: "uppercase" },
  freeImgApplyBtn: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 16, paddingVertical: 12, borderRadius: 999, backgroundColor: colors.primary },


  row: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8, paddingHorizontal: 10, backgroundColor: colors.surfaceMuted, borderRadius: 10, marginTop: 6 },
  rowText: { flex: 1, fontSize: 13, color: colors.textMain },
  addBtn: { width: 44, height: 44, borderRadius: 12, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" },

  outlineBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 10, borderRadius: 10, borderWidth: 1, borderColor: colors.primary, backgroundColor: colors.primary + "08" },
  outlineBtnText: { fontSize: 12, fontWeight: "800", color: colors.primary },
  smallDangerBtn: { width: 44, height: 44, borderRadius: 10, backgroundColor: "#FCE9E5", alignItems: "center", justifyContent: "center" },

  toolRow: { flexDirection: "row", gap: 6, marginTop: 8, flexWrap: "wrap" },
  toolBtn: { paddingHorizontal: 10, paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, minWidth: 36, alignItems: "center", justifyContent: "center" },
  toolBtnActive: { backgroundColor: colors.primary, borderColor: colors.primary },

  galleryGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  galleryItem: { width: 72, height: 72, borderRadius: 10, overflow: "hidden", position: "relative" },
  galleryImg: { width: "100%", height: "100%" },
  galleryRemove: { position: "absolute", top: 4, right: 4, width: 20, height: 20, borderRadius: 10, backgroundColor: "rgba(0,0,0,0.6)", alignItems: "center", justifyContent: "center" },
  galleryAdd: { width: 72, height: 72, borderRadius: 10, borderWidth: 1, borderStyle: "dashed", borderColor: colors.primary, alignItems: "center", justifyContent: "center", backgroundColor: colors.primary + "08" },

  specTabCard: { backgroundColor: colors.surfaceMuted, borderRadius: 12, padding: 10, marginBottom: 8 },

  boxItemRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 },
  boxThumb: { width: 44, height: 44, borderRadius: 10, overflow: "hidden" },

  // Category & sub-category chips
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 },
  chip: { paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  chipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  chipText: { fontSize: 12, fontWeight: "700", color: colors.textMain },
  chipTextActive: { color: colors.primaryFg },

  // UPDATE 2 — Smart product-master search UI
  masterWrap: {
    marginBottom: 12, padding: 12, borderRadius: 14,
    borderWidth: 1, borderColor: colors.primary + "30",
    backgroundColor: colors.primary + "08",
  },
  masterHead: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8, flexWrap: "wrap" },
  masterTitle: { fontSize: 12, fontWeight: "800", color: colors.primary, letterSpacing: 0.4 },
  masterSub: { fontSize: 10, color: colors.textMuted, fontWeight: "600" },
  masterInputRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: 12, paddingVertical: 10,
    borderRadius: 10, backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
  },
  masterInput: { flex: 1, fontSize: 13, color: colors.textMain, padding: 0 },
  masterDropdown: {
    marginTop: 8, borderRadius: 12,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
    overflow: "hidden",
    maxHeight: 340,
  },
  masterRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 10, paddingHorizontal: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  masterImg: { width: 44, height: 44, borderRadius: 8, backgroundColor: colors.surfaceMuted },
  masterName: { fontSize: 13, fontWeight: "800", color: colors.textMain, lineHeight: 17 },
  masterMeta: { fontSize: 10, color: colors.textMuted, marginTop: 2, fontWeight: "600" },
  masterSpecs: { fontSize: 10, color: colors.primary, marginTop: 2, fontWeight: "600" },
  masterPrice: { fontSize: 13, fontWeight: "800", color: colors.primary, marginBottom: 2 },
  masterEmpty: {
    marginTop: 8, padding: 10, borderRadius: 10,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    flexDirection: "row", alignItems: "center", gap: 8,
  },
  masterEmptyText: { flex: 1, fontSize: 11, color: colors.textMuted, fontWeight: "600" },
  masterSrcBadge: {
    flexDirection: "row", alignItems: "center", gap: 3,
    paddingHorizontal: 6, paddingVertical: 2,
    borderRadius: 4, backgroundColor: "#7C3AED14",
    borderWidth: 1, borderColor: "#7C3AED30",
  },
  masterSrcBadgeText: { fontSize: 9, fontWeight: "800", color: "#7C3AED", letterSpacing: 0.3 },
  masterSrcBadgeDeodap: {
    flexDirection: "row", alignItems: "center", gap: 3,
    paddingHorizontal: 6, paddingVertical: 2,
    borderRadius: 4, backgroundColor: "#0F766E14",
    borderWidth: 1, borderColor: "#0F766E30",
  },
  masterSrcBadgeDeodapText: { fontSize: 9, fontWeight: "800", color: "#0F766E", letterSpacing: 0.3 },
  masterChipsRow: {
    flexDirection: "row", gap: 6, marginTop: 8, flexWrap: "wrap",
  },
  masterChip: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999,
    borderWidth: 1, borderColor: colors.primary + "40",
    backgroundColor: colors.surface,
  },
  masterChipActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  masterChipText: { fontSize: 11, fontWeight: "800", color: colors.primary, letterSpacing: 0.2 },
  masterChipTextActive: { color: "#fff" },
  masterChipCount: {
    minWidth: 18, paddingHorizontal: 5,
    borderRadius: 8, backgroundColor: colors.primary + "18",
    alignItems: "center", justifyContent: "center",
  },
  masterChipCountActive: { backgroundColor: "rgba(255,255,255,0.28)" },
  masterChipCountText: { fontSize: 9, fontWeight: "900", color: colors.primary },
  masterChipCountTextActive: { color: "#fff" },
  tplRow: { flexDirection: "row", gap: 8, marginBottom: 10, flexWrap: "wrap" },
  tplBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 10,
    borderWidth: 1, borderColor: colors.primary + "40",
    backgroundColor: colors.primary + "10",
  },
  tplBtnGhost: { backgroundColor: colors.surface, borderColor: colors.border },
  tplBtnText: { fontSize: 11, fontWeight: "800", color: colors.primary },
  // Device Identity — inline validation styles
  inputError: { borderColor: "#B3261E", backgroundColor: "#B3261E10" },
  imeiHintRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    marginTop: 6, paddingHorizontal: 4,
  },
  imeiHintText: { fontSize: 11, fontWeight: "700" },
  // Scan-button row (Serial / IMEI-1 / IMEI-2)
  scanRow: { flexDirection: "row", alignItems: "stretch", gap: 8 },
  scanBtn: {
    width: 44, height: 44, borderRadius: 10,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: colors.primary + "50",
    backgroundColor: colors.primary + "12",
  },
  // "Specs not found" banner
  notFoundBanner: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 10, paddingHorizontal: 12,
    marginBottom: 10, borderRadius: 10,
    backgroundColor: "#FFF4E5",
    borderWidth: 1, borderColor: "#FFD59E",
  },
  notFoundText: { flex: 1, fontSize: 12, fontWeight: "700", color: "#8A5300", lineHeight: 17 },

  // Clothes-only block
  clothesBlock: { marginTop: 12, padding: 12, borderRadius: 12, backgroundColor: colors.primary + "08", borderWidth: 1, borderColor: colors.primary + "30" },

  // AI button
  aiBtn: { marginTop: 12, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 12, borderRadius: 12, backgroundColor: "#7C3AED" },
  aiBtnText: { color: "#fff", fontSize: 13, fontWeight: "800", letterSpacing: 0.2 },
  aiBtnSecondary: {
    marginTop: 8, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingVertical: 10, borderRadius: 12,
    backgroundColor: "transparent", borderWidth: 1, borderColor: colors.primary,
  },
  aiBtnSecondaryText: { color: colors.primary, fontSize: 12.5, fontWeight: "800", letterSpacing: 0.2 },
  aiHint: { fontSize: 11, color: colors.textMuted, marginTop: 8, lineHeight: 15 },

  // AI reference image row
  aiRefRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    marginTop: 12, padding: 10,
    backgroundColor: colors.surface, borderRadius: 12,
    borderWidth: 1, borderColor: colors.border,
  },
  aiRefThumb: { width: 48, height: 60, borderRadius: 8, overflow: "hidden", backgroundColor: colors.surfaceMuted },
  aiRefLabel: { fontSize: 12, fontWeight: "800", color: colors.textMain, letterSpacing: 0.2 },
  aiRefSub: { fontSize: 10.5, color: colors.textMuted, marginTop: 1, lineHeight: 14 },
  aiRefBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 6,
    borderRadius: 999, borderWidth: 1, borderColor: colors.primary,
    backgroundColor: colors.brand100,
  },
  aiRefBtnText: { fontSize: 11, fontWeight: "800", color: colors.primary, letterSpacing: 0.2 },
});
