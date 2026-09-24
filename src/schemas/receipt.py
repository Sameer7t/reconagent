from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator


class ReceiptItem(BaseModel):
    """A single line item from a receipt."""

    model_config = ConfigDict(extra="ignore")

    item_code: Optional[str] = Field(
        default=None,
        description=(
            "Product, item, SKU, service, or inventory code explicitly printed for "
            "this line item. Extract the code exactly as shown, preserving letters "
            "and digits. Do not confuse the item code with quantity, price, receipt "
            "number, tax ID, or transaction number. Return null if no item code is "
            "present or it cannot be reliably identified."
        )
    )
    description: str = Field(
        description=(
            "Name or description of the purchased product or service exactly as "
            "printed on the receipt. Extract only text that identifies the item. "
            "Do not include prices, quantities, taxes, discounts, or payment information "
            "as part of the description."
        )
    )

    quantity: Optional[Decimal] = Field(
        default=None,
        description=(
            "Quantity of this item explicitly shown on the receipt. "
            "Return a numeric value only. If the quantity is missing, unreadable, "
            "or cannot be determined reliably, return null. "
            "Do not calculate or infer the quantity."
        )
    )

    unit_price: Optional[Decimal] = Field(
        default=None,
        description=(
            "Price per single unit of this item explicitly shown on the receipt. "
            "Return a numeric value without currency symbols or formatting characters. "
            "Do not confuse the unit price with the line-item total. "
            "If the unit price is not explicitly shown or cannot be determined reliably, "
            "return null. Do not calculate it from other values."
        )
    )

    total: Optional[Decimal] = Field(
        default=None,
        description=(
            "Total price for this specific line item as explicitly printed on the receipt. "
            "Return a numeric value without currency symbols. "
            "Do not confuse this with the subtotal, tax, discount, or receipt grand total. "
            "Do not calculate quantity multiplied by unit_price. "
            "If the line-item total is not explicitly shown or cannot be determined reliably, "
            "return null."
        )
    )

    discount: Optional[Decimal] = Field(
        default=None,
        description=(
            "Discount amount explicitly applied to this specific line item. "
            "Return the numeric discount amount only. If a percentage discount "
            "is shown but no corresponding discount amount is explicitly printed, "
            "return null rather than calculating the amount."
        )
    )

    @field_validator("quantity", "unit_price", "total", "discount", mode="before")
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
            except (InvalidOperation, ValueError):
                return None
        return v


class Receipt(BaseModel):
    """Structured representation of a receipt."""

    model_config = ConfigDict(extra="ignore")

    vendor_name: Optional[str] = Field(
        default=None,
        description=(
            "Name of the business, store, merchant, or vendor that issued the receipt. "
            "Prefer the business name printed in the receipt header. "
            "Do not use the cashier name, customer name, address, phone number, "
            "or payment provider as the vendor name. "
            "Return null if the vendor name is not reliably identifiable."
        )
    )

    receipt_number: Optional[str] = Field(
        default=None,
        description=(
            "Unique identifier assigned to the receipt or transaction, such as a "
            "receipt number, invoice number, transaction number, or reference number. "
            "Prefer a value explicitly labeled as the receipt or transaction identifier. "
            "Do not mistake a phone number, tax ID, terminal ID, authorization code, "
            "date, or barcode number for the receipt number unless the document clearly "
            "identifies it as the receipt or transaction identifier."
        )
    )

    purchase_order_number: Optional[str] = Field(
        default=None,
        description=(
            "Purchase order reference associated with this receipt or delivery note. "
            "Extract the PO number exactly as displayed. Return null if no PO "
            "reference is present on the receipt."
        )
    )

    date: Optional[str] = Field(
        default=None,
        description=(
            "Extract ONLY the transaction date printed on the receipt. "
            "The value must contain a calendar date (day, month, and year, or "
            "a clearly identifiable date format supported by the document). "
            "DO NOT extract or infer a time, time-of-day, timestamp, or time-only "
            "value such as '10:30 AM', '14:25', or '10:30'. "
            "A time without a calendar date MUST return null. "
            "Do not use the transaction time, processing time, print time, or any "
            "other time-related value as the date. "
            "Preserve the date exactly as printed when possible and do not invent "
            "missing date components. If the date is ambiguous, incomplete, "
            "unreadable, or cannot be reliably distinguished from a time or "
            "timestamp, return null."
            )
    )

    currency: Optional[str] = Field(
        default=None,
        description=(
            "Currency explicitly indicated on the receipt, using the visible currency "
            "code or symbol when reliably identifiable, such as USD, EUR, GBP, PKR, $, "
            "€, or £. Do not infer the currency solely from the vendor's location. "
            "Return null when no reliable currency indication is present."
        )
    )

    subtotal: Optional[Decimal] = Field(
        default=None,
        description=(
            "The amount explicitly labeled 'Subtotal' or an equivalent label such as "
            "'Sub Total'. Do NOT use 'Total Sales', 'Total', 'Grand Total', 'Amount Due', "
            "'Cash', or any other final-sales amount as the subtotal. "
            "If the receipt does not explicitly show a subtotal, return null even if "
            "the sum of the line items equals a plausible subtotal. Never calculate "
            "or infer the subtotal from line items."
        )
    )

    discount_percentage: Optional[Decimal] = Field(
        default=None,
        description=(
            "Discount percentage explicitly printed on the receipt, such as 10% "
            "or 7.5%. Return the numeric percentage without the '%' symbol. "
            "Do not calculate the percentage from discount and subtotal. "
            "Return null if no discount percentage is explicitly shown."
        )
    )

    discount_amount: Optional[Decimal] = Field(
        default=None,
        description=(
            "Monetary discount amount explicitly printed on the receipt. "
            "Return the numeric amount without currency symbols. "
            "Do not calculate the amount from a discount percentage. "
            "Return null when only a percentage is shown and no monetary "
            "discount amount is explicitly printed."
        )
    )

    tax: Optional[Decimal] = Field(
        default=None,
        description=(
            "Total tax amount explicitly printed on the receipt, such as sales tax, VAT, "
            "GST, or equivalent. Return a numeric value without currency symbols. "
            "Do not calculate tax from the subtotal or line items. "
            "If multiple tax amounts are clearly presented as components of the receipt's "
            "total tax, they may be combined; otherwise extract the explicitly stated "
            "tax amount. Return null if tax is not shown."
        )
    )

    service_charge: Optional[Decimal] = Field(
        default=None,
        description=(
            "Service charge or gratuity amount explicitly printed on the receipt, such as "
            "'Service Charge 10%', 'Serv Charge', 'SVC', 'Tip', or similar dining/hospitality surcharge. "
            "Return the monetary numeric amount without currency symbols. "
            "Do not calculate from percentages unless an explicit monetary amount is printed. "
            "Return null if no service charge is present."
        )
    )

    rounding_adjustment: Optional[Decimal] = Field(
        default=None,
        description=(
            "Rounding adjustment explicitly applied to the transaction to round "
            "the payable amount. This may be a positive or negative monetary "
            "adjustment and may appear with labels such as 'Rounding', "
            "'Rounding Adjustment', 'Round Off', 'Round-off', or similar. "
            "Return the signed numeric amount exactly as represented on the receipt. "
            "For example, '-0.02' means the total was reduced by 0.02, while "
            "'0.03' means the total was increased by 0.03. "
            "Do not calculate or infer a rounding adjustment if it is not explicitly "
            "shown. Return null when no rounding adjustment is present."
        )
    )

    total: Optional[Decimal] = Field(
        default=None,
        description=(
            "Final amount actually payable or charged to the customer. Prefer an "
            "explicit final payable amount identified by labels such as 'Total', "
            "'Grand Total', 'Amount Due', 'Net Total', or equivalent. "
            "When multiple fields named 'Total', 'Total Sales', or similar appear, "
            "determine which value represents the final transaction amount by "
            "examining the surrounding labels and payment section. "
            "Do not select 'Cash', 'Amount Tendered', or 'Change' as the total. "
            "Do not calculate the total from line items. "
            "If the document contains contradictory or ambiguous total fields, "
            "select the value most clearly associated with the final amount payable; "
            "if no reliable final total can be identified, return null."
        )
    )

    total_quantity: Optional[Decimal] = Field(
        default=None,
        description=(
            "Total quantity explicitly printed by the receipt, such as a value "
            "labeled 'Total Qty' or 'Total Quantity'. Extract the printed value "
            "only. Do not calculate it by summing item quantities."
        )
    )

    items: list[ReceiptItem] = Field(
        default_factory=list,
        description=(
            "List of distinct products or services purchased in the transaction. "
            "Create one ReceiptItem for each identifiable line item. "
            "Do not include subtotal, tax, discounts, payment methods, totals, "
            "store information, or promotional text as items. "
            "If no purchased items can be reliably identified, return an empty list."
        )
    )

    @field_validator(
        "subtotal", "discount_percentage", "discount_amount",
        "tax", "service_charge", "rounding_adjustment", "total", "total_quantity",
        mode="before"
    )
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
            except (InvalidOperation, ValueError):
                return None
        return v