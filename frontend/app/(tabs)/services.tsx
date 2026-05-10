// Services tab — reuses the same Shop screen component, but the screen detects
// the route via usePathname() and locks the mode to "services". This keeps
// all existing services logic (filters, GPS, cards) without code duplication.
import ShopScreen from "./shop";
export default ShopScreen;
