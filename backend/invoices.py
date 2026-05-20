"""GST Invoice generator.

Provides:
- compute_gst(amount, gst_inclusive=True, gst_pct=18) -> dict
- invoice_number_for(tx) -> str  (deterministic, no DB sequence required)
- invoice_html(tx, owner, branding, counter_party=None) -> str
- invoice_pdf(tx, owner, branding, counter_party=None) -> bytes

The same data shape is used for both HTML and PDF so the values match exactly.
GST regime: India 18% (CGST 9% + SGST 9% intra-state by default; IGST 18%
inter-state if buyer state != company state).
"""
from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, Optional

from reportlab.lib import colors as rl_colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)


GST_PCT_DEFAULT = 18.0  # India standard rate

# Transaction types that yield "tax invoices" (B2C goods/services sold by platform)
INVOICEABLE_TAX_INVOICE = {"order", "service_booking", "registration_fee"}
# Transaction types that yield "commission/income statements" (paid TO the user).
INVOICEABLE_COMMISSION = {
    "vendor_sale", "service_earning",
    "shop_commission", "service_commission", "admin_credit", "transfer_in",
    "transfer_out", "withdrawal", "admin_debit", "system_deposit",
    # L1..L10 MLM payouts — users CAN download an invoice copy. The
    # gross/GST/net split is rendered inline so they can reconcile against
    # the gross they expected and the net actually credited.
    "referral_payout", "level_payout",
}

# Types where GST/CGST/SGST rows MUST be SUPPRESSED on the printed invoice.
# These are internal-app money movements that are NOT a taxable supply:
#   • system_deposit  — admin UTR direct-add (Direct-Added bucket)
#   • admin_credit / admin_debit — manual wallet adjustments
#   • transfer_in / transfer_out — peer-to-peer wallet transfer
#   • withdrawal     — user pulling THEIR OWN money to bank/UPI
#
# For these, the printed statement only shows the gross amount as
# "Net payment" with no taxable-value / IGST / CGST / SGST breakdown.
NO_GST_INVOICE_TYPES = {
    "system_deposit",
    "admin_credit", "admin_debit",
    "transfer_in", "transfer_out",
    "withdrawal",
}


def is_invoiceable(tx: Dict[str, Any]) -> bool:
    """Whether this txn supports an invoice/statement document."""
    t = (tx.get("type") or "").lower()
    return t in INVOICEABLE_TAX_INVOICE or t in INVOICEABLE_COMMISSION


def is_tax_invoice(tx: Dict[str, Any]) -> bool:
    """True if this is a taxable supply by the company (CGST/SGST/IGST applies)."""
    return (tx.get("type") or "").lower() in INVOICEABLE_TAX_INVOICE


def compute_gst(
    amount: float,
    *,
    gst_inclusive: bool = True,
    gst_pct: float = GST_PCT_DEFAULT,
    inter_state: bool = False,
) -> Dict[str, float]:
    """Return GST split for an `amount`.

    `gst_inclusive=True` means `amount` already INCLUDES GST (most B2C cases).
    Returns dict with: gross, taxable, cgst, sgst, igst, gst_pct.
    """
    amount = abs(float(amount))
    if gst_inclusive:
        taxable = round(amount / (1.0 + gst_pct / 100.0), 2)
        gst = round(amount - taxable, 2)
        gross = amount
    else:
        taxable = amount
        gst = round(amount * (gst_pct / 100.0), 2)
        gross = round(taxable + gst, 2)

    if inter_state:
        igst = gst
        cgst = sgst = 0.0
    else:
        cgst = round(gst / 2.0, 2)
        sgst = round(gst - cgst, 2)  # avoid floating drift
        igst = 0.0
    return {
        "gross": gross,
        "taxable": taxable,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "gst_total": round(cgst + sgst + igst, 2),
        "gst_pct": gst_pct,
    }


def invoice_number_for(tx: Dict[str, Any]) -> str:
    """Deterministic invoice number derived from the transaction id and type.
    Format: INV/<TXTYPE-SHORT>/<YYYYMM>/<6CHAR>"""
    t = (tx.get("type") or "TX").upper().replace("_", "")[:4] or "TX"
    yyyymm = (tx.get("created_at") or "")[:7].replace("-", "") or "000000"
    short = (tx.get("id") or "0").replace("-", "")[:6].upper()
    if is_tax_invoice(tx):
        prefix = "INV"
    else:
        prefix = "STMT"
    return f"{prefix}/{t}/{yyyymm}/{short}"


def _company_block(b: Dict[str, Any]) -> Dict[str, str]:
    return {
        "name": b.get("business_name") or b.get("app_name") or "Network RuPay Solutions Pvt Ltd",
        "address": b.get("business_address") or "",
        "city": b.get("business_city") or "",
        "state": b.get("business_state") or "",
        "pincode": b.get("business_pincode") or "",
        "gstin": b.get("business_gst") or "",
        "email": b.get("support_email") or "",
        "phone": b.get("support_phone") or "",
    }


def _customer_block(owner: Optional[Dict[str, Any]], counter_party: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    o = owner or {}
    return {
        "name": o.get("name") or "—",
        "email": o.get("email") or "—",
        "phone": o.get("phone") or "—",
        "referral_code": o.get("referral_code") or "",
        "gstin": "",  # reserved for future B2B GSTIN capture
    }


def _description_for(tx: Dict[str, Any], counter_party: Optional[Dict[str, Any]] = None) -> str:
    t = (tx.get("type") or "").lower()
    cp_name = (counter_party or {}).get("name") or ""
    desc = tx.get("description") or ""
    if t == "order":
        return f"E-commerce order ({desc})"
    if t == "service_booking":
        return f"Service booking{(' from ' + cp_name) if cp_name else ''}"
    if t == "service_earning":
        return f"Service earnings (provider share){(' for booking from ' + cp_name) if cp_name else ''}"
    if t == "registration_fee":
        return "Network membership / registration fee"
    if t == "referral_payout":
        return f"Referral commission (level {tx.get('level','-')}){(' from ' + cp_name) if cp_name else ''}"
    if t == "level_payout":
        return f"Level payout (level {tx.get('level','-')})"
    if t == "vendor_sale":
        return "Vendor share (post-platform-commission)"
    if t == "shop_commission":
        return "Platform margin on e-commerce sale"
    if t == "service_commission":
        return "Platform margin on service booking"
    if t == "admin_credit":
        return "Manual wallet credit by admin"
    if t == "admin_debit":
        return "Manual wallet debit by admin"
    if t == "transfer_in":
        return "Wallet credit from peer transfer"
    if t == "transfer_out":
        return "Wallet debit via peer transfer"
    if t == "withdrawal":
        return "Wallet withdrawal to bank/UPI"
    if t == "system_deposit":
        return "Admin direct cash deposit to system wallet"
    return desc or t.replace("_", " ").title()


def _make_invoice_data(
    tx: Dict[str, Any],
    owner: Optional[Dict[str, Any]],
    branding: Dict[str, Any],
    counter_party: Optional[Dict[str, Any]] = None,
    gst_inclusive: bool = True,
    gst_pct: float = GST_PCT_DEFAULT,
) -> Dict[str, Any]:
    company = _company_block(branding)
    customer = _customer_block(owner, counter_party)
    inter_state = False  # default intra-state; reserved for future GSTIN-based switching
    is_tax = is_tax_invoice(tx)
    amt = abs(float(tx.get("amount") or 0))

    is_no_gst = (tx.get("type") or "") in NO_GST_INVOICE_TYPES
    # If the txn was written with explicit gross / gst snapshots (referral
    # payouts in particular), use THOSE — that's the ground truth captured
    # at credit-time. Recomputing from `amount` (net) gives a wrong gross
    # because round-trip 18% math doesn't reverse cleanly (₹328 × 1.18 ≠ ₹400).
    stored_gross = tx.get("gross_amount")
    stored_gst = tx.get("gst_amount")
    stored_pct = tx.get("gst_pct")
    has_stored_split = (stored_gross is not None and stored_gst is not None)

    if is_no_gst:
        # Internal-app movement (UTR deposit, wallet adjustment, peer transfer,
        # withdrawal). NO GST inflation — gross == net == the actual txn amount.
        gst = compute_gst(amt, gst_inclusive=True, gst_pct=gst_pct, inter_state=inter_state)
        title = "PAYMENT STATEMENT"
    elif has_stored_split:
        # Use the stored split written by _credit_payout — the gross, gst, and
        # net are authoritative and reflect what actually moved in the ledger.
        gross_v = float(stored_gross)
        gst_v = float(stored_gst)
        taxable_v = round(gross_v - gst_v, 2)
        pct = float(stored_pct) if stored_pct is not None else gst_pct
        if inter_state:
            cgst_v = sgst_v = 0.0
            igst_v = gst_v
        else:
            cgst_v = round(gst_v / 2.0, 2)
            sgst_v = round(gst_v - cgst_v, 2)
            igst_v = 0.0
        gst = {
            "gross": gross_v,
            "taxable": taxable_v,
            "cgst": cgst_v,
            "sgst": sgst_v,
            "igst": igst_v,
            "gst_total": gst_v,
            "gst_pct": pct,
        }
        title = "TAX INVOICE" if is_tax else "PAYMENT STATEMENT"
    elif is_tax:
        gst = compute_gst(amt, gst_inclusive=gst_inclusive, gst_pct=gst_pct, inter_state=inter_state)
        title = "TAX INVOICE"
    else:
        # Commission / statement — fallback for txns without stored split.
        # Treat amount as GST-EXCLUSIVE gross (matches level-payout semantics:
        # configured payout_l1=₹400 IS the gross, GST ₹72 carved out = net ₹328).
        gst = compute_gst(amt, gst_inclusive=False, gst_pct=gst_pct, inter_state=inter_state)
        title = "PAYMENT STATEMENT"

    return {
        "title": title,
        "is_tax_invoice": is_tax,
        "invoice_no": invoice_number_for(tx),
        "issue_date": (tx.get("created_at") or "")[:10],
        "company": company,
        "customer": customer,
        "tx": tx,
        "description": _description_for(tx, counter_party),
        "amount": amt,
        "gst": gst,
        "utr": tx.get("reference_number") or tx.get("razorpay_payment_id") or "",
        "method": tx.get("payment_method") or ("Wallet" if amt and (tx.get("type") in ("order", "service_booking", "transfer_out", "withdrawal")) else "—"),
        "counter_party": counter_party or {},
        "footer_note": (
            "This is a system-generated tax invoice and does not require a physical signature."
            if is_tax else
            "This is a payment / commission statement. Tax liability, if any, rests with the recipient as per applicable Income-Tax Act and GST law."
        ),
    }


# --------------------- HTML ---------------------
def invoice_html(
    tx: Dict[str, Any],
    owner: Optional[Dict[str, Any]],
    branding: Dict[str, Any],
    counter_party: Optional[Dict[str, Any]] = None,
) -> str:
    d = _make_invoice_data(tx, owner, branding, counter_party)
    c, cu, gst = d["company"], d["customer"], d["gst"]
    # Skip GST rows entirely for internal-app movements (UTR deposit, admin
    # wallet adjustment, peer transfer, withdrawal). For these, the invoice
    # is just a receipt of the gross transfer with no tax breakdown.
    suppress_gst = (tx.get("type") or "") in NO_GST_INVOICE_TYPES
    inter = (not suppress_gst) and gst["igst"] > 0
    gst_rows = ""
    if suppress_gst:
        gst_rows = ""  # explicit no-op for readability
    elif inter:
        gst_rows = f"<tr><td>IGST @ {gst['gst_pct']:.0f}%</td><td class='r'>₹ {gst['igst']:.2f}</td></tr>"
    else:
        gst_rows = (
            f"<tr><td>CGST @ {gst['gst_pct']/2:.1f}%</td><td class='r'>₹ {gst['cgst']:.2f}</td></tr>"
            f"<tr><td>SGST @ {gst['gst_pct']/2:.1f}%</td><td class='r'>₹ {gst['sgst']:.2f}</td></tr>"
        )
    # Pre-compute labels and values OUTSIDE the f-string (Python 3.11
    # doesn't allow conditional expressions in format specifiers, e.g.
    # `{x if cond else y:.2f}` raises "Invalid format specifier").
    _is_level_payout = (tx.get("type") or "") in ("referral_payout", "level_payout") and not suppress_gst
    _total_label = (
        "Total payable" if d["is_tax_invoice"]
        else ("Net credited to wallet" if _is_level_payout else "Net payment")
    )
    _total_value = float(gst["taxable"] if _is_level_payout else gst["gross"])
    _gross_note = (
        f"<tr><td style='font-size:10px;color:#666'>Gross payout (before GST)</td>"
        f"<td class='r' style='font-size:10px;color:#666'>₹ {gst['gross']:.2f}</td></tr>"
        if _is_level_payout else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{d['title']} · {d['invoice_no']}</title>
<style>
*{{box-sizing:border-box;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}}
body{{margin:0;padding:24px;color:#1c2520;background:#fff}}
.wrap{{max-width:760px;margin:0 auto;border:1px solid #e5e4e0;border-radius:14px;overflow:hidden}}
.head{{background:#143D2E;color:#fff;padding:22px 28px;display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px}}
.head h1{{margin:0;font-size:22px;letter-spacing:1px}}
.head .meta{{font-size:12px;text-align:right;line-height:1.6}}
.body{{padding:24px 28px}}
.row{{display:flex;gap:24px;flex-wrap:wrap;margin-bottom:18px}}
.box{{flex:1 1 260px;border:1px solid #e5e4e0;border-radius:10px;padding:14px}}
.box h3{{margin:0 0 8px;font-size:11px;letter-spacing:1.5px;color:#6B7280;text-transform:uppercase}}
.box p{{margin:0;font-size:13px;line-height:1.5}}
.box strong{{font-weight:700}}
.tbl{{width:100%;border-collapse:collapse;margin-top:14px;font-size:13px}}
.tbl th,.tbl td{{border:1px solid #e5e4e0;padding:10px 12px;text-align:left}}
.tbl th{{background:#f3f1ec;font-size:11px;letter-spacing:1px;text-transform:uppercase;color:#6B7280}}
.tbl .r{{text-align:right}}
.summ{{width:60%;margin-left:auto;margin-top:14px;font-size:13px;border-collapse:collapse}}
.summ td{{padding:6px 10px;border-bottom:1px solid #ebebe6}}
.summ .total td{{font-weight:800;border-top:2px solid #1C2520;border-bottom:none;padding-top:10px;font-size:15px}}
.foot{{font-size:11px;color:#6B7280;margin-top:22px;text-align:center;line-height:1.5}}
.badge{{display:inline-block;background:#E57A44;color:#fff;padding:4px 10px;border-radius:999px;font-size:10px;letter-spacing:1.5px;font-weight:800;margin-bottom:6px}}
@media print{{body{{padding:0}}.wrap{{border:none;border-radius:0}}}}
</style></head>
<body><div class="wrap">
  <div class="head">
    <div>
      <div class="badge">{d['title']}</div>
      <h1>{c['name']}</h1>
      <div style="font-size:11px;opacity:0.85;margin-top:4px">{c['address']}{(', '+c['city']) if c['city'] else ''}{(', '+c['state']) if c['state'] else ''}{(' - '+c['pincode']) if c['pincode'] else ''}</div>
      <div style="font-size:11px;opacity:0.85">{('GSTIN: '+c['gstin']) if c['gstin'] else 'GSTIN: Not registered'} · {c['email']} · {c['phone']}</div>
    </div>
    <div class="meta">
      <div><strong>Invoice #</strong></div>
      <div>{d['invoice_no']}</div>
      <div style="margin-top:6px"><strong>Date</strong></div>
      <div>{d['issue_date']}</div>
    </div>
  </div>
  <div class="body">
    <div class="row">
      <div class="box"><h3>Billed to</h3>
        <p><strong>{cu['name']}</strong></p>
        <p>{cu['email']}</p>
        <p>{cu['phone']}</p>
        {('<p>Member ID: '+cu['referral_code']+'</p>') if cu['referral_code'] else ''}
      </div>
      <div class="box"><h3>Payment</h3>
        <p><strong>Method:</strong> {d['method']}</p>
        <p><strong>Status:</strong> {(d['tx'].get('status') or '').upper()}</p>
        {('<p><strong>UTR:</strong> '+d['utr']+'</p>') if d['utr'] else ''}
        <p><strong>Txn ID:</strong> {(d['tx'].get('id') or '')[:16].upper()}</p>
      </div>
    </div>
    <table class="tbl">
      <thead><tr><th>Description</th><th class="r">Amount</th></tr></thead>
      <tbody>
        <tr><td>{d['description']}</td><td class="r">₹ {(gst['gross'] if suppress_gst else gst['taxable']):.2f}</td></tr>
      </tbody>
    </table>
    <table class="summ">
      {"" if suppress_gst else f"<tr><td>Taxable value</td><td class='r'>₹ {gst['taxable']:.2f}</td></tr>"}
      {gst_rows}
      <tr class="total"><td>{_total_label}</td><td class="r">₹ {_total_value:.2f}</td></tr>
      {_gross_note}
    </table>
    <div class="foot">{d['footer_note']}</div>
  </div>
</div></body></html>"""


# --------------------- PDF (ReportLab Platypus) ---------------------
def invoice_pdf(
    tx: Dict[str, Any],
    owner: Optional[Dict[str, Any]],
    branding: Dict[str, Any],
    counter_party: Optional[Dict[str, Any]] = None,
) -> bytes:
    d = _make_invoice_data(tx, owner, branding, counter_party)
    c, cu, gst = d["company"], d["customer"], d["gst"]
    # Same suppression rule as the HTML invoice — internal app movements
    # (UTR deposit, admin adjustment, peer transfer, withdrawal) print
    # without any GST breakdown.
    suppress_gst = (tx.get("type") or "") in NO_GST_INVOICE_TYPES
    inter = (not suppress_gst) and gst["igst"] > 0

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"{d['title']} {d['invoice_no']}",
    )
    ss = getSampleStyleSheet()
    h_white = ParagraphStyle("h_white", parent=ss["Heading1"], textColor=rl_colors.white, fontSize=18, leading=22, spaceAfter=2)
    sub_white = ParagraphStyle("sub_white", parent=ss["Normal"], textColor=rl_colors.white, fontSize=9, leading=12)
    badge = ParagraphStyle("badge", parent=ss["Normal"], textColor=rl_colors.white, fontSize=8, leading=10, spaceAfter=4)
    h3 = ParagraphStyle("h3", parent=ss["Normal"], fontSize=8, leading=10, textColor=rl_colors.HexColor("#6B7280"), spaceAfter=4)
    body = ParagraphStyle("body", parent=ss["Normal"], fontSize=10, leading=13)
    body_b = ParagraphStyle("body_b", parent=body, fontName="Helvetica-Bold")
    foot = ParagraphStyle("foot", parent=ss["Normal"], fontSize=8, textColor=rl_colors.HexColor("#6B7280"), alignment=1)

    story = []

    # Header band
    addr_line = c['address'] + (", " + c['city'] if c['city'] else "") + (", " + c['state'] if c['state'] else "") + (" - " + c['pincode'] if c['pincode'] else "")
    gst_line = f"GSTIN: {c['gstin']}" if c['gstin'] else "GSTIN: Not registered"
    contact_line = f"{c['email']}  ·  {c['phone']}".strip(" ·")
    head_left = [
        Paragraph(f"<b>{d['title']}</b>", badge),
        Paragraph(c['name'], h_white),
        Paragraph(addr_line, sub_white),
        Paragraph(f"{gst_line}  ·  {contact_line}", sub_white),
    ]
    head_right = [
        Paragraph("<b>Invoice #</b>", sub_white),
        Paragraph(d['invoice_no'], sub_white),
        Paragraph("<b>Date</b>", sub_white),
        Paragraph(d['issue_date'] or "—", sub_white),
    ]
    head_tbl = Table([[head_left, head_right]], colWidths=[120 * mm, 50 * mm])
    head_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), rl_colors.HexColor("#143D2E")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    story.append(head_tbl)
    story.append(Spacer(1, 12))

    # Billed-to + Payment boxes
    billed_to = [
        Paragraph("BILLED TO", h3),
        Paragraph(f"<b>{cu['name']}</b>", body_b),
        Paragraph(cu['email'], body),
        Paragraph(cu['phone'], body),
    ]
    if cu['referral_code']:
        billed_to.append(Paragraph(f"Member ID: {cu['referral_code']}", body))

    payment_box = [
        Paragraph("PAYMENT", h3),
        Paragraph(f"<b>Method:</b> {d['method']}", body),
        Paragraph(f"<b>Status:</b> {(d['tx'].get('status') or '').upper()}", body),
    ]
    if d['utr']:
        payment_box.append(Paragraph(f"<b>UTR:</b> {d['utr']}", body))
    payment_box.append(Paragraph(f"<b>Txn ID:</b> {(d['tx'].get('id') or '')[:16].upper()}", body))

    info = Table([[billed_to, payment_box]], colWidths=[85 * mm, 85 * mm])
    info.setStyle(TableStyle([
        ("BOX", (0, 0), (0, 0), 0.5, rl_colors.HexColor("#E5E4E0")),
        ("BOX", (1, 0), (1, 0), 0.5, rl_colors.HexColor("#E5E4E0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(info)
    story.append(Spacer(1, 12))

    # Line item table
    items = [
        ["Description", "Amount"],
        [d["description"], f"{(gst['gross'] if suppress_gst else gst['taxable']):.2f}"],
    ]
    items_tbl = Table(items, colWidths=[130 * mm, 40 * mm])
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#F3F1EC")),
        ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.HexColor("#6B7280")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#E5E4E0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(items_tbl)

    # Summary
    summary: List[List[str]] = []
    if not suppress_gst:
        summary.append(["Taxable value", f"₹ {gst['taxable']:.2f}"])
        if inter:
            summary.append([f"IGST @ {gst['gst_pct']:.0f}%", f"₹ {gst['igst']:.2f}"])
        else:
            summary.append([f"CGST @ {gst['gst_pct']/2:.1f}%", f"₹ {gst['cgst']:.2f}"])
            summary.append([f"SGST @ {gst['gst_pct']/2:.1f}%", f"₹ {gst['sgst']:.2f}"])
    summary.append([
        ("Total payable" if d["is_tax_invoice"] else "Net payment"),
        f"₹ {gst['gross']:.2f}",
    ])
    summ_tbl = Table(summary, colWidths=[100 * mm, 40 * mm], hAlign="RIGHT")
    summ_tbl.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, rl_colors.HexColor("#EBEBE6")),
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, rl_colors.HexColor("#1C2520")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 11),
        ("TOPPADDING", (0, -1), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(Spacer(1, 8))
    story.append(summ_tbl)

    story.append(Spacer(1, 22))
    story.append(Paragraph(d["footer_note"], foot))

    doc.build(story)
    return buf.getvalue()
