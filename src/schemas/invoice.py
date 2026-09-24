from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator



class InvoiceParty(BaseModel):
    """Information identifying a vendor or buyer listed on the invoice."""
    name: Optional[str] = Field(
        default=None,
        description=(
            "Full legal or displayed name of the company or organization. "
            "Extract exactly as shown on the invoice. Do not infer or normalize "
            "the name if it is unclear."
        ),
    )

    address: Optional[str] = Field(
        default=None,
        description=(
            "Complete mailing or business address associated with the party. "
            "Preserve the address as displayed, including street, city, "
            "state/province, postal code, and country when available."
        ),
    )


class InvoiceItem(BaseModel):
    """A single line item appearing on the invoice."""


    description: str = Field(
        description=(
            "Description of the goods or services for this line item. "
            "Extract the description exactly as presented on the invoice."
        ),
    )

    product_code: Optional[str] = Field(
        default=None,
        description=(
            "Product identifier, SKU, item number, part number, service code, "
            "or other item code shown for this line. Return null when not present."
        ),
    )

    quantity: Optional[Decimal] = Field(
        default=None,
        description=(
            "Number of units, items, hours, or other measurable quantity "
            "billed for this line. Preserve decimal quantities when shown."
        ),
    )

    unit: Optional[str] = Field(
        default=None,
        description=(
            "Unit associated with the quantity, such as 'pcs', 'kg', 'hours', "
            "'box', 'each', or 'unit'. Return null when not explicitly stated."
        ),
    )

    unit_price: Optional[Decimal] = Field(
        default=None,
        description=(
            "Price charged for one unit of this line item before any "
            "line-level discount or tax, when the invoice provides a unit price."
        ),
    )

    unit_discount: Optional[Decimal] = Field(
        default=None,
        description=(
            "Discount applied specifically to this line item. Preserve the "
            "invoice's representation as a monetary amount when possible. "
            "Do not confuse a percentage discount with a monetary discount."
        ),
    )

    unit_tax: Optional[Decimal] = Field(
        default=None,
        description=(
            "Tax amount applied specifically to this line item. Extract the "
            "monetary tax amount when explicitly shown."
        ),
    )

    line_total: Optional[Decimal] = Field(
        default=None,
        description=(
            "Final monetary price/amount for this individual line item as printed "
            "on the invoice. This is the total amount attributable to the item line, "
            "typically calculated as quantity × unit price, after any discounts or "
            "adjustments applied specifically to that line. Do not include invoice-level "
            "discounts, taxes, shipping, fees, rounding adjustments, or other charges "
            "unless they are explicitly included in this line item's printed total."
        ),
    )

    @field_validator("quantity", "unit_price", "unit_discount", "unit_tax", "line_total", mode="before")
    @classmethod
    def clean_decimal(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, str):
            clean_str = v.strip().replace(",", "")
            if clean_str.endswith("-"):
                clean_str = "-" + clean_str[:-1]
            try:
                return Decimal(clean_str)
            except Exception:
                return None
        return v


class Invoice(BaseModel):

    """Structured representation of an extracted invoice."""


    invoice_number: Optional[str] = Field(
        default=None,
        description=(
            "Unique invoice identifier assigned by the vendor, such as "
            "'INV-10025'. Extract the invoice number, not the purchase order "
            "number, customer number, or account number."
        ),
    )

    invoice_date: Optional[date] = Field(
        default=None,
        description=(
            "Date the invoice was issued. Convert the displayed date into "
            "ISO date format (YYYY-MM-DD) when the date can be determined "
            "unambiguously."
        ),
    )

    due_date: Optional[date] = Field(
        default=None,
        description=(
            "Payment due date stated on the invoice. Convert to ISO date "
            "format (YYYY-MM-DD) when unambiguous. Return null if absent."
        ),
    )

    purchase_order_number: Optional[str] = Field(
        default=None,
        description=(
            "Purchase order reference associated with the invoice. Extract "
            "the PO number exactly as displayed. Return null if no PO reference "
            "is present."
        ),
    )

    vendor: InvoiceParty = Field(
        description=(
            "Company or organization issuing the invoice and requesting payment."
        ),
    )

    buyer: InvoiceParty = Field(
        description=(
            "Company or organization being billed or purchasing the goods "
            "or services."
        ),
    )

    currency: Optional[str] = Field(
        default=None,
        description=(
            "Currency used for the invoice monetary amounts. Prefer the "
            "three-letter ISO 4217 code when it can be unambiguously identified, "
            "such as USD, EUR, or GBP. Do not guess when the currency is unclear."
        ),
    )
    
    total_quantity: Optional[Decimal] = Field(
        default=None,
        description=(
            "Total quantity represented by all invoice line items, when an "
            "overall quantity is explicitly stated on the invoice. Extract the "
            "stated total quantity exactly as shown. Return null if no total "
            "quantity is provided. Do not calculate or infer this value by "
            "summing line-item quantities, especially when different units of "
            "measurement are used."
        ),
    )

    items: list[InvoiceItem] = Field(
        default_factory=list,
        description=(
            "All billable line items appearing on the invoice. Include every "
            "distinct product or service line and preserve the invoice order."
        ),
    )

    subtotal: Optional[Decimal] = Field(
        default=None,
        description=(
            "Invoice subtotal before invoice-level discounts, shipping, tax, "
            "and other additional charges, according to the invoice."
        ),
    )

    total_discount: Optional[Decimal] = Field(
        default=None,
        description=(
            "Invoice-level discount applied to the overall invoice. This is "
            "separate from discounts belonging to individual line items."
        ),
    )

    shipping: Optional[Decimal] = Field(
        default=None,
        description=(
            "Shipping, freight, delivery, or transportation charge applied "
            "to the invoice."
        ),
    )

    total_tax: Optional[Decimal] = Field(
        default=None,
        description=(
            "Total invoice-level tax amount. Use this for tax shown as a "
            "summary amount rather than tax already represented at individual "
            "line-item level."
        ),
    )

    rounding_adjustment: Optional[Decimal] = Field(
        default=None,
        description=(
            "Explicit rounding adjustment shown on the invoice, whether "
            "positive or negative. Do not calculate a rounding adjustment "
            "yourself if the invoice does not explicitly show one."
        ),
    )

    total: Optional[Decimal] = Field(
        default=None,
        description=(
            "Final amount payable or total amount stated on the invoice after "
            "discounts, shipping, tax, rounding adjustments, and other "
            "applicable charges."
        ),
    )

    payment_terms: Optional[str] = Field(
        default=None,
        description=(
            "Payment terms stated on the invoice, such as 'Net 30', "
            "'Due on receipt', or '50% upfront, 50% on delivery'. "
            "Preserve the wording as displayed."
        ),
    )

    notes: Optional[str] = Field(
        default=None,
        description=(
            "Additional invoice notes, instructions, comments, or terms that "
            "do not belong to another structured field. Preserve relevant "
            "information without inventing content."
        ),
    )

    invoice_status: Optional[str] = Field(
        default=None,
        description=(
            "Explicit status of the invoice when stated on the document, "
            "such as 'Paid', 'Unpaid', 'Pending', 'Overdue', 'Cancelled', "
            "or 'Draft'. Do not infer the status solely from the due date "
            "or other fields."
        ),
    )

    @field_validator("total_quantity", "subtotal", "total_discount", "shipping", "total_tax", "rounding_adjustment", "total", mode="before")
    @classmethod
    def clean_decimal(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, str):
            clean_str = v.strip().replace(",", "")
            if clean_str.endswith("-"):
                clean_str = "-" + clean_str[:-1]
            try:
                return Decimal(clean_str)
            except Exception:
                return None
        return v