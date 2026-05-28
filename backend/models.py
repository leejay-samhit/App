"""
Pydantic request/response models extracted from server.py.

This module is a pure data-class container -- no business logic, no I/O.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=6)
    phone: Optional[str] = None
    referral_code: Optional[str] = None  # sponsor code


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class BankUpdate(BaseModel):
    upi_id: Optional[str] = None
    bank_account: Optional[str] = None
    ifsc: Optional[str] = None
    account_holder: Optional[str] = None


class WithdrawalRequest(BaseModel):
    amount: float = Field(gt=0)


class StyledText(BaseModel):
    text: Optional[str] = ""
    bold: Optional[bool] = False
    font_size: Optional[int] = None       # px; None = use default
    align: Optional[str] = "left"         # "left" | "center" | "right"


class WhatsInBoxItem(BaseModel):
    name: Optional[str] = ""
    image_data_url: Optional[str] = ""    # base64 thumbnail


class SpecRow(BaseModel):
    label: Optional[str] = ""
    value: Optional[str] = ""


class SpecTab(BaseModel):
    name: Optional[str] = ""              # e.g. "General", "Display", "Battery"
    rows: List[SpecRow] = Field(default_factory=list)


class ProductCreate(BaseModel):
    name: str
    price: float
    image_url: str
    description: Optional[str] = ""
    stock: int = 100
    category: Optional[str] = None
    is_published: bool = True
    vendor_id: Optional[str] = None  # admin can assign to a vendor

    # ── Rich detail-page fields (all optional for backward compat) ──
    brand: Optional[str] = ""
    sub_features: Optional[List[str]] = Field(default_factory=list)
    images: Optional[List[str]] = Field(default_factory=list)  # up to 10 base64 / urls
    # Styled marketing copy (each block has text + bold/size/align)
    price_summary: Optional[StyledText] = None
    protection_summary: Optional[StyledText] = None
    warranty_summary: Optional[StyledText] = None
    delivery_summary: Optional[StyledText] = None
    # Structured attributes
    attrs_brand: Optional[str] = ""
    attrs_os: Optional[str] = ""
    attrs_ram: Optional[str] = ""
    attrs_cpu_model: Optional[str] = ""
    attrs_cpu_speed: Optional[str] = ""
    attrs_storage: Optional[str] = ""
    extra_attrs: Optional[Dict[str, str]] = Field(default_factory=dict)  # admin-added KV pairs
    # Spec tables (each tab has rows of label/value)
    spec_tabs: Optional[List[SpecTab]] = Field(default_factory=list)
    # What's in the Box
    whats_in_box: Optional[List[WhatsInBoxItem]] = Field(default_factory=list)
    # Clothes-specific (only meaningful when category == "Clothes")
    sub_category: Optional[str] = None      # male | female | boys | girls
    clothing_size: Optional[str] = None     # S | M | L | XL | XXL


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    image_url: Optional[str] = None
    description: Optional[str] = None
    stock: Optional[int] = None
    category: Optional[str] = None
    is_published: Optional[bool] = None
    vendor_id: Optional[str] = None
    brand: Optional[str] = None
    sub_features: Optional[List[str]] = None
    images: Optional[List[str]] = None
    price_summary: Optional[StyledText] = None
    protection_summary: Optional[StyledText] = None
    warranty_summary: Optional[StyledText] = None
    delivery_summary: Optional[StyledText] = None
    attrs_brand: Optional[str] = None
    attrs_os: Optional[str] = None
    attrs_ram: Optional[str] = None
    attrs_cpu_model: Optional[str] = None
    attrs_cpu_speed: Optional[str] = None
    attrs_storage: Optional[str] = None
    extra_attrs: Optional[Dict[str, str]] = None
    spec_tabs: Optional[List[SpecTab]] = None
    whats_in_box: Optional[List[WhatsInBoxItem]] = None
    sub_category: Optional[str] = None
    clothing_size: Optional[str] = None


class BrandingPayload(BaseModel):
    app_name: Optional[str] = None
    tagline: Optional[str] = None
    login_subtitle: Optional[str] = None
    payment_hero: Optional[str] = None
    pending_hero: Optional[str] = None
    colors: Optional[Dict[str, str]] = None
    font: Optional[str] = None
    tabs: Optional[List[Dict[str, Any]]] = None
    # ─── App-launch splash overlay (Feb-2026) ───
    # Admin can upload an in-app splash image (shown for `splash_duration_ms`
    # after the native splash dismisses). Recommended size: 1080×1920 px,
    # ≤500 KB after base64. Pass `splash_image: null` to remove the overlay.
    splash_image: Optional[str] = None      # base64 data URI or http URL
    splash_duration_ms: Optional[int] = None  # 1000..10000
    splash_bg: Optional[str] = None         # hex colour
    # ─── Payment methods config (Feb-2026) ───
    payment_methods: Optional[Dict[str, Any]] = None
    # ─── Premium theme extensions (June 2026) ───
    gradient: Optional[Dict[str, str]] = None     # {start, middle, end, glow}
    button_style: Optional[str] = None            # rounded | pill | square
    home_banner_b64: Optional[str] = None         # base64 PNG/JPG for home hero


class GoogleExchange(BaseModel):
    session_id: str
    referral_code: Optional[str] = None


class CreateOrderResponse(BaseModel):
    order_id: str
    amount_paise: int
    currency: str
    key_id: str
    is_mock: bool


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class PaymentFailureRequest(BaseModel):
    razorpay_order_id: Optional[str] = None
    reason: Optional[str] = None


class WalletTransfer(BaseModel):
    recipient: str = Field(..., description="Recipient email or referral code")
    amount: float = Field(..., gt=0)
    note: Optional[str] = None


class WithdrawalCompleteRequest(BaseModel):
    reference_number: Optional[str] = ""


class WithdrawalRejectRequest(BaseModel):
    reason: Optional[str] = ""


class WithdrawalBatchRequest(BaseModel):
    ids: List[str]
    reference_prefix: Optional[str] = ""


class AdminUserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    role: Optional[str] = None  # "user" or "admin"
    admin_role: Optional[str] = None  # "super_admin" | "manager" | "support"
    # NOTE: wallet_balance and total_earned are intentionally NOT editable here.
    # All money movements MUST go through /admin/users/{id}/wallet (credit/debit)
    # which atomically debits the system-wallet's `direct_added` bucket — this
    # enforces the "only money that's been deposited can be paid out" invariant.
    registration_paid: Optional[bool] = None
    upi_id: Optional[str] = None
    bank_account: Optional[str] = None
    ifsc: Optional[str] = None
    account_holder: Optional[str] = None


class AdminPasswordReset(BaseModel):
    new_password: str = Field(min_length=6)


class AdminCreate(BaseModel):
    name: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=6)
    admin_role: str = "manager"  # super_admin | manager | support
    phone: Optional[str] = None


class PromoteRequest(BaseModel):
    admin_role: str = "manager"  # super_admin | manager | support


class SuperPasswordSet(BaseModel):
    new_password: str
    current_password: Optional[str] = None  # required if one is already set


class SuperPasswordVerify(BaseModel):
    super_password: str


class DangerPinSet(BaseModel):
    new_pin: str
    current_pin: Optional[str] = None  # required if one is already set


class WipeUsersRequest(BaseModel):
    keep_admins: bool = True
    danger_pin: str  # required — unified danger-zone PIN


class WipeAllRequest(BaseModel):
    danger_pin: str
    confirm_phrase: Optional[str] = None  # require user to type "RESET" client-side


class SettingsUpdate(BaseModel):
    registration_fee: Optional[float] = Field(default=None, ge=0)
    payout_l1: Optional[float] = Field(default=None, ge=0)
    payout_l2: Optional[float] = Field(default=None, ge=0)
    payout_l3: Optional[float] = Field(default=None, ge=0)
    payout_l4: Optional[float] = Field(default=None, ge=0)
    payout_l5: Optional[float] = Field(default=None, ge=0)
    payout_l6: Optional[float] = Field(default=None, ge=0)
    payout_l7: Optional[float] = Field(default=None, ge=0)
    payout_l8: Optional[float] = Field(default=None, ge=0)
    payout_l9: Optional[float] = Field(default=None, ge=0)
    payout_l10: Optional[float] = Field(default=None, ge=0)
    directs_required: Optional[int] = Field(default=None, ge=1, le=20)
    auto_approve_on_payment: Optional[bool] = None


class CartItem(BaseModel):
    product_id: str
    qty: int = Field(gt=0)


class CartRemove(BaseModel):
    product_id: str


class KYCSubmit(BaseModel):
    full_name: str
    aadhaar: str
    pan: str
    aadhaar_front: Optional[str] = None  # base64 data URL ("data:image/jpeg;base64,...")
    aadhaar_back: Optional[str] = None
    pan_image: Optional[str] = None
    selfie: Optional[str] = None


class KYCReject(BaseModel):
    reason: str


class ApprovalReject(BaseModel):
    category: str  # one of REJECT_CATEGORIES keys
    reason: Optional[str] = None  # optional remarks; required for the new "other" category


class AdminCreateUserRequest(BaseModel):
    name: str
    email: EmailStr
    password: str = Field(min_length=6)
    phone: Optional[str] = None
    referral_code: Optional[str] = None  # sponsor code
    mark_paid_offline: bool = True  # admin collected the fee outside the app
    # Canonical source tag for accountability. Admin chooses how the fee
    # actually flowed to the system wallet so the ledger and breakdown card
    # match reality. Defaults to "offline_cash" for backward compat with
    # callers that don't send this field.
    #   "offline_cash" — admin took cash in person
    #   "razorpay"     — fee already collected via Razorpay outside the app
    #   "upi_manual"   — fee collected via direct UPI transfer (UTR on file)
    registration_source: Optional[str] = "offline_cash"


class ExtraDocsSubmit(BaseModel):
    cibil_report: Optional[str] = None
    bank_statement: Optional[str] = None
    income_proof: Optional[str] = None
    other: Optional[str] = None


class BlockRequest(BaseModel):
    reason: str


class WalletAdjust(BaseModel):
    amount: float = Field(gt=0)
    type: str
    reason: str  # required remarks for audit trail


class SystemWalletDeposit(BaseModel):
    amount: float = Field(gt=0)
    utr: str = Field(min_length=4, max_length=40)
    bank_ref: Optional[str] = None
    remarks: Optional[str] = None


class TxnStatusUpdate(BaseModel):
    status: str


class OrderStatusUpdate(BaseModel):
    status: str


class TakeBackupRequest(BaseModel):
    note: Optional[str] = None


class RestoreBackupRequest(BaseModel):
    danger_pin: str


class TicketCreateRequest(BaseModel):
    subject: str
    category: str = "other"
    message: str
    attachment_b64: Optional[str] = None  # optional image screenshot


class PublicTicketCreateRequest(BaseModel):
    """Guest (unauthenticated) ticket submission from the pre-login Contact page."""
    email: Optional[str] = None                # validated in-route → returns 400 (not 422) if missing/empty
    name: Optional[str] = None
    subject: str = "ISSUE"
    category: str = "other"                    # one of the standard slugs OR "other"
    custom_category: Optional[str] = None      # free-text label when category=="other"
    message: Optional[str] = None              # validated in-route → 400 on missing/short/long


class TicketReplyRequest(BaseModel):
    message: str
    attachment_b64: Optional[str] = None


class TicketUpdateRequest(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None  # admin user id or null to unassign


class PublicTicketLookupRequest(BaseModel):
    """Guest looks up their own tickets by email (no OTP — informational only)."""
    email: str


class PublicTicketReplyRequest(BaseModel):
    """Guest replies to their own ticket — must supply the same email used at creation."""
    email: str
    message: str


class RevealPhoneRequest(BaseModel):
    """Customer pays a small fee + GST to reveal a service-provider's phone."""
    accept_terms: bool = False


class AdminTallyWithdrawRequest(BaseModel):
    """Admin debits System Wallet for off-platform usage / account tally."""
    amount: float
    note: str
    bucket: Optional[str] = None  # default = "direct_added"


class AddressUpdateRequest(BaseModel):
    """User can edit their delivery / contact address."""
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None


# ─────────────── Provider Availability (June 2026) ─────────────── #
class ProviderAvailabilityRequest(BaseModel):
    """Service-provider self-toggle for visibility status. Independent of
    live-location sharing — this is purely an "I'm taking jobs / I'm busy /
    I'm offline" flag the provider controls from their dashboard.
    """
    status: str  # "available" | "busy" | "offline"


# ─────────────── User location capture (foreground GPS) ────────── #
class UserLocationUpdate(BaseModel):
    """Customer 'Use my location' tap — captures one foreground GPS sample.
    Used to prioritise nearby providers. Not for background tracking.
    """
    latitude: float
    longitude: float
    accuracy_m: Optional[float] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None


# ─────────────── Service Subcategory CRUD ─────────────────────── #
class ServiceSubcategoryCreate(BaseModel):
    parent_id: str
    name: str
    slug: Optional[str] = None
    icon: Optional[str] = None
    image_b64: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    active: bool = True


class ServiceSubcategoryUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    image_b64: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None
    active: Optional[bool] = None


class CategoryReorderRequest(BaseModel):
    """Bulk reorder — admin drags & drops categories or subcategories.
    Items: [{id: str, sort_order: int}, …]"""
    items: List[Dict[str, Any]]


# ─────────────── AI Generation (Emergent LLM Key) ─────────────── #
class AITextRequest(BaseModel):
    """Generate / improve service descriptions, category copy, marketing
    text. `kind` hints the prompt scaffolding to use server-side."""
    kind: str  # "service_description" | "category_description" | "marketing" | "service_title" | "improve"
    prompt: str
    existing: Optional[str] = None  # used by "improve" — original text to refine
    tone: Optional[str] = "professional"  # professional | friendly | bold | concise
    max_words: Optional[int] = 80


class AIImageRequest(BaseModel):
    """Generate a category icon / service banner image with Nano Banana.
    Returns base64 PNG that the admin can save into the category doc."""
    prompt: str
    style: Optional[str] = "flat-icon"  # flat-icon | banner | illustration | hero


class PaymentGatewayPayload(BaseModel):
    key_id: str
    key_secret: str


class VendorApplyRequest(BaseModel):
    shop_name: str
    gst_number: Optional[str] = ""
    pan_number: Optional[str] = ""
    bank_name: Optional[str] = ""
    bank_account: Optional[str] = ""
    bank_ifsc: Optional[str] = ""
    description: Optional[str] = ""


class VendorRejectRequest(BaseModel):
    reason: Optional[str] = ""


class ServiceApplyRequest(BaseModel):
    service_name: str = Field(min_length=2, max_length=80)
    service_category: str = Field(min_length=2, max_length=40)  # e.g. "Plumber", "Tutor"
    category_id: Optional[str] = None  # FK → service_categories.id (preferred)
    pincode: str = Field(pattern=r"^\d{6}$")
    charge: float = Field(ge=0, le=1_000_000)
    description: Optional[str] = Field(default=None, max_length=500)
    languages: Optional[List[str]] = None  # subset of {"en","te","hi","ta"}


class ServiceCategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    slug: Optional[str] = Field(default=None, max_length=40)
    icon: Optional[str] = Field(default="briefcase", max_length=40)  # Feather icon name
    color: Optional[str] = Field(default="#2563EB", max_length=12)
    sort_order: Optional[int] = 0
    active: Optional[bool] = True
    # ─── Premium image fields (June 2026) ───
    image_b64: Optional[str] = None        # category card image (small, ~256x256)
    banner_b64: Optional[str] = None       # category banner image (1200x400)
    description: Optional[str] = Field(default=None, max_length=500)


class ServiceCategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=40)
    slug: Optional[str] = Field(default=None, max_length=40)
    icon: Optional[str] = Field(default=None, max_length=40)
    color: Optional[str] = Field(default=None, max_length=12)
    sort_order: Optional[int] = None
    active: Optional[bool] = None
    image_b64: Optional[str] = None
    banner_b64: Optional[str] = None
    description: Optional[str] = Field(default=None, max_length=500)


class ProviderLocationUpdate(BaseModel):
    """Provider broadcasts their current foreground GPS coordinates."""
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: Optional[float] = Field(default=None, ge=0, le=50000)
    sharing: Optional[bool] = True  # set to false to stop sharing


class DistributorAreaAssign(BaseModel):
    """Bulk-assign one or more pincodes to a distributor user.
    Each pincode is exclusive: if it's already mapped to another distributor,
    that mapping is silently *overwritten* (the API caller is the source of
    truth)."""
    pincodes: List[str] = Field(default_factory=list, max_length=10000)


class DistributorPromote(BaseModel):
    is_distributor: bool


class ServiceRejectRequest(BaseModel):
    reason: Optional[str] = None


class ServiceBookRequest(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=300)
    scheduled_date: Optional[str] = None  # ISO date the customer wants service


