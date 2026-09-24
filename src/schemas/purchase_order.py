from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict
from pydantic import BaseModel, Field, ConfigDict, field_validator


class PurchaseOrderItem(BaseModel):
    """A single line item from a purchase order."""

    model_config = ConfigDict(extra="ignore")

    description: str = Field(
        description=(
            "Exact description of the product or service ordered. "
            "Preserve the wording from the document as closely as possible. "
            "Do not infer or invent a description if it is unclear."
        )
    )

    product_code: Optional[str] = Field(
        default=None,
        description=(
            "Product, item, SKU, part, or service code associated with the line item. "
            "Return null when no identifiable code is present."
        )
    )

    quantity: Optional[Decimal] = Field(
        default=None,
        description=(
            "Quantity ordered for this line item. Extract numeric values only. "
            "Preserve decimal quantities when present. Return null if the quantity "
            "cannot be reliably determined."
        )
    )

    unit: Optional[str] = Field(
        default=None,
        description=(
            "Unit of measurement for the quantity, such as pcs, units, kg, "
            "hours, containers, cartons, or each. Return null if not stated."
        )
    )

    unit_price: Optional[Decimal] = Field(
        default=None,
        description=(
            "Price for one unit of this line item before applicable taxes, "
            "discounts, or other adjustments, when the document provides a "
            "separate unit price. Return null if unavailable."
        )
    )

    discount: Optional[Decimal] = Field(
        default=None,
        description=(
            "Discount amount applied specifically to this line item. "
            "Return null if no line-level discount is stated."
        )
    )

    tax: Optional[Decimal] = Field(
        default=None,
        description=(
            "Tax amount applied specifically to this line item, if separately "
            "shown. Return null when unavailable or when tax is only provided "
            "at the purchase-order level."
        )
    )

    line_total: Optional[Decimal] = Field(
        default=None,
        description=(
            "Final monetary amount for this line item as stated on the purchase "
            "order, after any explicitly stated line-level discounts and before "
            "any separately stated document-level adjustments."
        )
    )

    @field_validator("quantity", "unit_price", "discount", "tax", "line_total", mode="before")
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


class PurchaseOrder(BaseModel):
    """Structured representation of a purchase order."""

    model_config = ConfigDict(extra="ignore")

    purchase_order_number: Optional[str] = Field(
        default=None,
        description=(
            "Unique purchase order identifier or PO number exactly as shown "
            "on the document. Do not confuse it with an invoice number, "
            "quotation number, sales order number, or reference number."
        )
    )

    order_date: Optional[date] = Field(
        default=None,
        description=(
            "Date on which the purchase order was issued. Normalize the value "
            "to YYYY-MM-DD when the date can be determined reliably."
        )
    )

    delivery_date: Optional[date] = Field(
        default=None,
        description=(
            "Requested or expected delivery date stated on the purchase order. "
            "Return null if no delivery date is provided."
        )
    )

    vendor_name: Optional[str] = Field(
        default=None,
        description=(
            "Name of the supplier/vendor receiving the purchase order. "
            "Extract the legal or trading name shown on the document."
        )
    )

    vendor_address: Optional[str] = Field(
        default=None,
        description=(
            "Full vendor/supplier address as shown on the purchase order. "
            "Return null if unavailable."
        )
    )

    buyer_name: Optional[str] = Field(
        default=None,
        description=(
            "Name of the purchasing company, organization, or buyer issuing "
            "the purchase order."
        )
    )

    buyer_address: Optional[str] = Field(
        default=None,
        description=(
            "Address of the purchasing company or buyer, if stated."
        )
    )

    currency: Optional[str] = Field(
        default=None,
        description=(
            "Currency used for monetary amounts in the purchase order. "
            "Return the ISO 4217 currency code when it can be determined, "
            "such as USD, EUR, or GBP. Do not guess when ambiguous."
        )
    )

    items: list[PurchaseOrderItem] = Field(
        default_factory=list,
        description=(
            "All distinct product or service line items appearing in the "
            "purchase order. Preserve the document's line-item boundaries "
            "and do not omit repeated or zero-value lines."
        )
    )

    subtotal: Optional[Decimal] = Field(
        default=None,
        description=(
            "Purchase-order subtotal before document-level tax, discounts, "
            "shipping, rounding adjustments, or other additions/ deductions, "
            "when explicitly stated."
        )
    )

    discount: Optional[Decimal] = Field(
        default=None,
        description=(
            "Document-level discount applied to the purchase order. "
            "Do not include line-level discounts already represented in items."
        )
    )

    shipping: Optional[Decimal] = Field(
        default=None,
        description=(
            "Shipping, freight, delivery, or transportation charge added "
            "at the purchase-order level."
        )
    )

    tax: Optional[Decimal] = Field(
        default=None,
        description=(
            "Total document-level tax amount stated on the purchase order. "
            "Do not duplicate line-level tax amounts."
        )
    )

    rounding_adjustment: Optional[Decimal] = Field(
        default=None,
        description=(
            "Explicit rounding adjustment applied to the purchase-order total. "
            "This may be positive or negative. Return null when no rounding "
            "adjustment is stated."
        )
    )

    total: Optional[Decimal] = Field(
        default=None,
        description=(
            "Final purchase-order amount payable or ordered, exactly as stated "
            "on the document after applicable discounts, shipping, taxes, "
            "rounding adjustments, and other explicitly included charges."
        )
    )

    payment_terms: Optional[str] = Field(
        default=None,
        description=(
            "Payment terms stated on the purchase order, such as Net 30, "
            "Net 60, due on receipt, or another stated arrangement."
        )
    )

    delivery_terms: Optional[str] = Field(
        default=None,
        description=(
            "Delivery or shipping terms stated on the purchase order, such as "
            "FOB, CIF, EXW, or other Incoterms/shipping conditions."
        )
    )

    notes: Optional[str] = Field(
        default=None,
        description=(
            "Other relevant purchase-order instructions, notes, special "
            "conditions, or remarks that do not belong to another field."
        )
    )

    @field_validator("subtotal", "discount", "shipping", "tax", "rounding_adjustment", "total", mode="before")
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