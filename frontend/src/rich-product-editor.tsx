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

async function pickAndCompressImage(opts?: { aspect?: [number, number]; width?: number }) {
  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!perm.granted) {
    Alert.alert("Permission needed", "Please allow photo library access.");
    return null;
  }
  const r = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ImagePicker.MediaTypeOptions.Images,
    quality: 0.85,
    allowsEditing: true,
    aspect: opts?.aspect ?? [4, 3],
  });
  if (r.canceled || !r.assets?.[0]?.uri) return null;
  const m = await ImageManipulator.manipulateAsync(
    r.assets[0].uri,
    [{ resize: { width: opts?.width ?? 900 } }],
    { compress: 0.7, format: ImageManipulator.SaveFormat.JPEG, base64: true },
  );
  return m.base64 ? `data:image/jpeg;base64,${m.base64}` : null;
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
  visible, existing, onClose, onSaved, endpoints,
}: {
  visible: boolean;
  existing: RichProduct | null;
  onClose: () => void;
  onSaved: () => void;
  endpoints: RichProductEndpoints;
}) {
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
  // Track whether the user picked a preset category or chose "Other"
  const isPresetCat = (c: string) => (CATEGORY_OPTIONS as readonly string[]).includes(c) && c !== "Other";
  const [customCategory, setCustomCategory] = useState<boolean>(false);

  const [saving, setSaving] = useState(false);
  const [picking, setPicking] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);

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
    // If editing an existing product with a custom (non-preset) category,
    // open the free-text input automatically.
    setCustomCategory(!!e.category && !isPresetCat(e.category));
  }, [visible, existing?.id]);

  const onPickCover = async () => {
    setPicking(true);
    try {
      const data = await pickAndCompressImage({ aspect: [4, 3], width: 900 });
      if (data) setImageUrl(data);
    } catch (e) {
      Alert.alert("Image pick failed", formatApiError(e));
    } finally { setPicking(false); }
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

  const onAddSubFeature = () => {
    const t = newSubFeature.trim();
    if (!t) return;
    setSubFeatures([...subFeatures, t]);
    setNewSubFeature("");
  };

  const onAddExtraAttr = () => setExtraAttrs([...extraAttrs, { key: "", value: "" }]);
  const onAddSpecTab = () => setSpecTabs([...specTabs, { name: `Tab ${specTabs.length + 1}`, rows: [] }]);
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

  const onGenerateAI = async () => {
    if (!isClothes) return;
    if (!subCategory) {
      Alert.alert("Pick a sub-category", "Please select Male, Female, Boys or Girls first.");
      return;
    }
    if (!imageUrl) {
      Alert.alert("Reference image required", "Please upload a basic photo of the clothes first (Cover image).");
      return;
    }
    Alert.alert(
      "Generate AI catalog photos?",
      "This will REPLACE all current gallery images with 5 AI-generated photos of an Indian model wearing the garment. The cover image is preserved. Continue?",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Generate",
          style: "default",
          onPress: async () => {
            setAiBusy(true);
            try {
              const res: any = await api.post("/products/ai-image", {
                image_data_url: imageUrl,
                gender: subCategory,
                category: "Clothes",
                size: clothingSize || undefined,
                count: 5,
              });
              const imgs: string[] = Array.isArray(res?.data?.images) ? res.data.images : [];
              if (!imgs.length) {
                Alert.alert("No images", "AI did not return any images. Please try again with a clearer reference photo.");
                return;
              }
              // Replace gallery completely (cap to 10)
              setGalleryImages(imgs.slice(0, 10));
              Alert.alert("Done", `Generated ${imgs.length} AI image${imgs.length === 1 ? "" : "s"} and replaced the gallery.`);
            } catch (e) {
              Alert.alert("AI generation failed", formatApiError(e));
            } finally {
              setAiBusy(false);
            }
          },
        },
      ],
    );
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
        is_published: published,
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
        sub_category: isClothes ? (subCategory || undefined) : undefined,
        clothing_size: isClothes ? (clothingSize || undefined) : undefined,
      };
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
              <TouchableOpacity onPress={onPickCover} style={modalStyles.imagePick} testID="product-image-pick">
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
              <Text style={modalStyles.fieldLabel}>Name</Text>
              <TextInput value={name} onChangeText={setName} style={modalStyles.input} testID="product-name" />
              <Text style={modalStyles.fieldLabel}>Price (₹)</Text>
              <TextInput value={price} onChangeText={setPrice} keyboardType="decimal-pad" style={modalStyles.input} testID="product-price" />
              <Text style={modalStyles.fieldLabel}>Stock</Text>
              <TextInput value={stock} onChangeText={setStock} keyboardType="number-pad" style={modalStyles.input} testID="product-stock" />
              <Text style={modalStyles.fieldLabel}>Category</Text>
              <View style={sectionStyles.chipRow}>
                {CATEGORY_OPTIONS.map((opt) => {
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
                          if (opt !== "Clothes") {
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
                  </View>
                  <Text style={modalStyles.fieldLabel}>Size</Text>
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

                  {/* AI Image Generator */}
                  <TouchableOpacity
                    onPress={onGenerateAI}
                    disabled={aiBusy}
                    style={[sectionStyles.aiBtn, aiBusy && { opacity: 0.7 }]}
                    testID="product-ai-generate"
                  >
                    {aiBusy ? (
                      <>
                        <ActivityIndicator color="#fff" />
                        <Text style={sectionStyles.aiBtnText}>Generating 5 AI photos…</Text>
                      </>
                    ) : (
                      <>
                        <Feather name="zap" size={16} color="#fff" />
                        <Text style={sectionStyles.aiBtnText}>Generate 5 AI Model Photos</Text>
                      </>
                    )}
                  </TouchableOpacity>
                  <Text style={sectionStyles.aiHint}>
                    Uses Gemini Nano Banana to create 5 photorealistic Indian model photos wearing your clothes.
                    Replaces all existing gallery images. Cover image is kept as-is.
                  </Text>
                </View>
              ) : null}

              <Text style={modalStyles.fieldLabel}>Description</Text>
              <TextInput value={description} onChangeText={setDescription} multiline style={[modalStyles.input, { minHeight: 70, paddingTop: 12 }]} testID="product-description" />
              <View style={modalStyles.switchRow}>
                <View style={{ flex: 1 }}>
                  <Text style={modalStyles.switchTitle}>Published</Text>
                  <Text style={modalStyles.switchSub}>Hidden products are not shown to users in the shop.</Text>
                </View>
                <Switch value={published} onValueChange={setPublished} testID="product-published" />
              </View>
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
  btn: { flex: 1, paddingVertical: 14, borderRadius: radii.button, alignItems: "center" },
});

const sectionStyles = StyleSheet.create({
  wrap: { marginBottom: 10, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, overflow: "hidden" },
  head: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14 },
  headIcon: { width: 32, height: 32, borderRadius: 10, backgroundColor: colors.primary + "12", alignItems: "center", justifyContent: "center" },
  headTitle: { fontSize: 14, fontWeight: "800", color: colors.textMain, letterSpacing: -0.2 },
  headSummary: { fontSize: 11, color: colors.textMuted, marginTop: 2 },
  body: { paddingHorizontal: 14, paddingBottom: 14, paddingTop: 4 },

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

  // Clothes-only block
  clothesBlock: { marginTop: 12, padding: 12, borderRadius: 12, backgroundColor: colors.primary + "08", borderWidth: 1, borderColor: colors.primary + "30" },

  // AI button
  aiBtn: { marginTop: 12, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, paddingVertical: 12, borderRadius: 12, backgroundColor: "#7C3AED" },
  aiBtnText: { color: "#fff", fontSize: 13, fontWeight: "800", letterSpacing: 0.2 },
  aiHint: { fontSize: 11, color: colors.textMuted, marginTop: 8, lineHeight: 15 },
});
