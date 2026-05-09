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


class ProductCreate(BaseModel):
    name: str
    price: float
    image_url: str
    description: Optional[str] = ""
    stock: int = 100
    category: Optional[str] = None
    is_published: bool = True
    vendor_id: Optional[str] = None  # admin can assign to a vendor


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    image_url: Optional[str] = None
    description: Optional[str] = None
    stock: Optional[int] = None
    category: Optional[str] = None
    is_published: Optional[bool] = None
    vendor_id: Optional[str] = None


class BrandingPayload(BaseModel):
    app_name: Optional[str] = None
    tagline: Optional[str] = None
    login_subtitle: Optional[str] = None
    payment_hero: Optional[str] = None
    pending_hero: Optional[str] = None
    colors: Optional[Dict[str, str]] = None
    font: Optional[str] = None
    tabs: Optional[List[Dict[str, Any]]] = None


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


class TicketReplyRequest(BaseModel):
    message: str
    attachment_b64: Optional[str] = None


class TicketUpdateRequest(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None  # admin user id or null to unassign


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


class ServiceCategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=40)
    slug: Optional[str] = Field(default=None, max_length=40)
    icon: Optional[str] = Field(default=None, max_length=40)
    color: Optional[str] = Field(default=None, max_length=12)
    sort_order: Optional[int] = None
    active: Optional[bool] = None


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
    pincodes: List[str] = Field(min_length=1, max_length=500)


class DistributorPromote(BaseModel):
    is_distributor: bool


class ServiceRejectRequest(BaseModel):
    reason: Optional[str] = None


class ServiceBookRequest(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=300)
    scheduled_date: Optional[str] = None  # ISO date the customer wants service


