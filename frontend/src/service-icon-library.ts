/**
 * Service category icon library (Nov-2026).
 *
 * The Edit Category screen already had a 21-icon strip; this is the same
 * picker with a much larger, labelled and grouped collection covering the
 * local trades Slangcart lists. Every entry is a Feather glyph, so icons stay
 * crisp at any size and need no download — and they render identically in the
 * admin list and the customer Services screen.
 *
 * AI icon generation and the colour picker are untouched: an admin can still
 * generate artwork instead of choosing from here.
 */
import type { Feather } from "@expo/vector-icons";

export type ServiceIcon = {
  name: keyof typeof Feather.glyphMap;
  /** What the trade is called, so the admin can search for it. */
  label: string;
};

export type ServiceIconGroup = {
  group: string;
  icons: ServiceIcon[];
};

export const SERVICE_ICON_GROUPS: ServiceIconGroup[] = [
  {
    group: "Construction & civil",
    icons: [
      { name: "tool", label: "Construction / contractor" },
      { name: "layers", label: "Masonry / tiles" },
      { name: "hexagon", label: "Cement / blocks" },
      { name: "grid", label: "Flooring / tiling" },
      { name: "square", label: "False ceiling" },
      { name: "triangle", label: "Roofing" },
      { name: "columns", label: "Pillars / structure" },
      { name: "box", label: "Material supply" },
      { name: "truck", label: "Earth moving / transport" },
      { name: "users", label: "Labour supply" },
      { name: "hard-drive", label: "Heavy machinery" },
      { name: "crop", label: "Surveying / measuring" },
    ],
  },
  {
    group: "Electrical & electronics",
    icons: [
      { name: "zap", label: "Electrician" },
      { name: "power", label: "Wiring / power" },
      { name: "battery-charging", label: "Inverter / battery" },
      { name: "cpu", label: "Electronics repair" },
      { name: "monitor", label: "TV / display repair" },
      { name: "tv", label: "Home theatre" },
      { name: "sun", label: "Solar panels" },
      { name: "radio", label: "Audio systems" },
      { name: "speaker", label: "Speakers / DJ" },
      { name: "smartphone", label: "Mobile repair" },
      { name: "tablet", label: "Tablet / laptop repair" },
      { name: "printer", label: "Printer service" },
    ],
  },
  {
    group: "Plumbing & water",
    icons: [
      { name: "droplet", label: "Plumber" },
      { name: "filter", label: "Water purifier" },
      { name: "thermometer", label: "Geyser / water heater" },
      { name: "umbrella", label: "Waterproofing" },
      { name: "cloud-drizzle", label: "Borewell / pumps" },
      { name: "disc", label: "Tank cleaning" },
    ],
  },
  {
    group: "Internet, networking & CCTV",
    icons: [
      { name: "wifi", label: "Internet / broadband" },
      { name: "share-2", label: "Networking / LAN" },
      { name: "server", label: "Server / data" },
      { name: "video", label: "CCTV cameras" },
      { name: "camera", label: "Camera installation" },
      { name: "eye", label: "Surveillance" },
      { name: "cast", label: "Dish / set-top box" },
      { name: "airplay", label: "Smart home" },
      { name: "terminal", label: "IT support" },
      { name: "code", label: "Software / web" },
    ],
  },
  {
    group: "Security & safety",
    icons: [
      { name: "shield", label: "Security services" },
      { name: "lock", label: "Locks / safes" },
      { name: "key", label: "Locksmith" },
      { name: "bell", label: "Alarm systems" },
      { name: "life-buoy", label: "Fire & safety" },
      { name: "user-check", label: "Guards / bouncers" },
    ],
  },
  {
    group: "Cooling, cleaning & home care",
    icons: [
      { name: "wind", label: "AC service / repair" },
      { name: "refresh-cw", label: "Fan / cooler repair" },
      { name: "trash-2", label: "Cleaning / housekeeping" },
      { name: "home", label: "Home services" },
      { name: "feather", label: "Pest control" },
      { name: "archive", label: "Packers & movers" },
      { name: "sliders", label: "Carpentry" },
      { name: "edit-3", label: "Painting" },
      { name: "pen-tool", label: "Interior design" },
      { name: "image", label: "Glass & aluminium" },
      { name: "settings", label: "Appliance repair" },
      { name: "clipboard", label: "Inspection / survey" },
    ],
  },
  {
    group: "Beauty, health & personal",
    icons: [
      { name: "scissors", label: "Salon / barber" },
      { name: "heart", label: "Beauty & spa" },
      { name: "smile", label: "Makeup artist" },
      { name: "activity", label: "Fitness trainer" },
      { name: "plus-square", label: "Medical / nursing" },
      { name: "user", label: "Personal care" },
    ],
  },
  {
    group: "Vehicles & logistics",
    icons: [
      { name: "truck", label: "Goods transport" },
      { name: "navigation", label: "Driver on call" },
      { name: "compass", label: "Towing / roadside" },
      { name: "package", label: "Courier / delivery" },
      { name: "map-pin", label: "Local pickup" },
      { name: "watch", label: "Vehicle service" },
    ],
  },
  {
    group: "Events, education & other",
    icons: [
      { name: "gift", label: "Event & decoration" },
      { name: "music", label: "Music / orchestra" },
      { name: "film", label: "Photography / video" },
      { name: "book", label: "Tuition / coaching" },
      { name: "coffee", label: "Catering / cooks" },
      { name: "shopping-bag", label: "Shop services" },
      { name: "briefcase", label: "General service" },
      { name: "phone-call", label: "On-call support" },
      { name: "star", label: "Premium service" },
      { name: "globe", label: "Travel & visa" },
      { name: "dollar-sign", label: "Finance / tax" },
      { name: "file-text", label: "Documentation" },
    ],
  },
];

/** Flat list — handy for validation and for the legacy single-strip layout. */
export const SERVICE_ICONS: ServiceIcon[] = SERVICE_ICON_GROUPS.flatMap((g) => g.icons);

/** Search across icon name AND trade label. */
export function searchServiceIcons(query: string): ServiceIconGroup[] {
  const q = query.trim().toLowerCase();
  if (!q) return SERVICE_ICON_GROUPS;
  return SERVICE_ICON_GROUPS.map((g) => ({
    group: g.group,
    icons: g.icons.filter(
      (i) => i.label.toLowerCase().includes(q) || i.name.toLowerCase().includes(q),
    ),
  })).filter((g) => g.icons.length > 0);
}
