"""
Reconciliation schemas, enums, policies, and result models.

This module defines the complete data model for the multi-stage reconciliation
engine, including:
- Business-configurable tolerances (ReconciliationPolicy)
- Status and confidence enums
- Discrepancy classification and severity
- Line-item match provenance
- Final reconciliation result packaging
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict


# ============================================================
# ENUMS
# ============================================================

class Severity(str, Enum):
    """Severity level for a reconciliation discrepancy."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReconciliationStatus(str, Enum):
    """Overall status of a reconciliation case."""
    MATCHED = "MATCHED"
    MATCHED_WITH_TOLERANCE = "MATCHED_WITH_TOLERANCE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INCOMPLETE = "INCOMPLETE"
    UNMATCHED = "UNMATCHED"
    ERROR = "ERROR"


class LinkingConfidence(str, Enum):
    """Confidence tier for document linking."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class MatchMethod(str, Enum):
    """Method used to match two line items across documents."""
    NORMALIZED_DESCRIPTION = "NORMALIZED_DESCRIPTION"
    SKU = "SKU"
    VENDOR_ITEM_CODE = "VENDOR_ITEM_CODE"
    FUZZY_DESCRIPTION = "FUZZY_DESCRIPTION"
    SEMANTIC = "SEMANTIC"
    UNMATCHED = "UNMATCHED"


class DiscrepancyType(str, Enum):
    """Taxonomy of cross-document reconciliation discrepancies."""

    # Internal Document Validation (Pre-Reconciliation Stage 0)
    CALCULATION_ERROR = "CALCULATION_ERROR"
    INTERNAL_MATH_ERROR = "INTERNAL_MATH_ERROR"

    # Header-level (Stage 1)
    VENDOR_MISMATCH = "VENDOR_MISMATCH"
    DOCUMENT_LINK_MISMATCH = "DOCUMENT_LINK_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"

    # Line-item matching (Stage 2)
    UNMATCHED_ITEM = "UNMATCHED_ITEM"

    # Quantity (Stage 3)
    INVOICE_QUANTITY_EXCEEDS_PO = "INVOICE_QUANTITY_EXCEEDS_PO"
    INVOICE_QUANTITY_EXCEEDS_RECEIPT = "INVOICE_QUANTITY_EXCEEDS_RECEIPT"
    INVOICE_QUANTITY_EXCEEDS_RECEIVED = "INVOICE_QUANTITY_EXCEEDS_RECEIVED"
    PO_QUANTITY_EXCEEDS_INVOICE = "PO_QUANTITY_EXCEEDS_INVOICE"
    RECEIVED_QUANTITY_EXCEEDS_PO = "RECEIVED_QUANTITY_EXCEEDS_PO"

    # Price (Stage 4)
    UNIT_PRICE_MISMATCH = "UNIT_PRICE_MISMATCH"

    # Financial (Stage 5)
    UNAUTHORIZED_CHARGE = "UNAUTHORIZED_CHARGE"
    SHIPPING_EXCEEDS_PO = "SHIPPING_EXCEEDS_PO"
    SUBTOTAL_MISMATCH = "SUBTOTAL_MISMATCH"
    TAX_VARIANCE = "TAX_VARIANCE"
    DISCOUNT_NOT_APPLIED = "DISCOUNT_NOT_APPLIED"
    TOTAL_MISMATCH = "TOTAL_MISMATCH"

    # Receipt (Stage 6)
    RECEIPT_SHORTAGE = "RECEIPT_SHORTAGE"
    RECEIPT_PRICE_MISMATCH = "RECEIPT_PRICE_MISMATCH"
    RECEIPT_TOTAL_MISMATCH = "RECEIPT_TOTAL_MISMATCH"

    # Duplicate detection (Stage 7)
    DUPLICATE_INVOICE = "DUPLICATE_INVOICE"

    # Document completeness
    MISSING_DOCUMENT = "MISSING_DOCUMENT"

    # Catch-all
    OTHER = "OTHER"


# ============================================================
# BUSINESS POLICY
# ============================================================

class ReconciliationPolicy(BaseModel):
    """
    Business rules and tolerances governing the reconciliation engine.

    All monetary tolerances use Decimal for financial precision.
    Different vendors or contracts can specify custom policies.
    """
    model_config = ConfigDict(extra="ignore")

    # Price tolerances
    price_tolerance: Decimal = Field(
        default=Decimal("0.02"),
        description="Maximum allowable absolute unit price variance."
    )
    price_percentage_tolerance: Decimal = Field(
        default=Decimal("0.0"),
        description=(
            "Maximum allowable percentage unit price variance. "
            "Set to 0.0 to require exact matches within absolute tolerance."
        )
    )

    # Quantity tolerance
    quantity_tolerance: Decimal = Field(
        default=Decimal("0.00"),
        description="Maximum allowable quantity variance (0 for discrete goods)."
    )

    # Financial tolerances
    subtotal_tolerance: Decimal = Field(
        default=Decimal("0.05"),
        description="Allowable subtotal variance between PO and Invoice."
    )
    shipping_tolerance: Decimal = Field(
        default=Decimal("0.00"),
        description="Allowable shipping increase over PO-authorized amount."
    )
    tax_tolerance: Decimal = Field(
        default=Decimal("0.05"),
        description="Allowable tax variance."
    )
    total_tolerance: Decimal = Field(
        default=Decimal("0.05"),
        description="Allowable grand total variance."
    )

    # Linking thresholds
    min_link_confidence_auto: float = Field(
        default=0.85,
        description="Minimum score for HIGH confidence auto-linking."
    )
    min_link_confidence_review: float = Field(
        default=0.50,
        description="Minimum score for MEDIUM confidence human review."
    )

    # Authorization policy
    allow_unauthorized_charges: bool = Field(
        default=False,
        description="Whether to permit invoice charges not present on the PO."
    )

    # Severity thresholds for rule-based assignment
    high_price_difference_threshold: Decimal = Field(
        default=Decimal("100.00"),
        description="Absolute price difference above which severity is HIGH."
    )
    high_price_percentage_threshold: Decimal = Field(
        default=Decimal("10.0"),
        description="Percentage price difference above which severity is HIGH."
    )
    critical_unauthorized_charge_threshold: Decimal = Field(
        default=Decimal("500.00"),
        description="Unauthorized charge amount above which severity is CRITICAL."
    )


# ============================================================
# DISCREPANCY MODEL
# ============================================================

class Discrepancy(BaseModel):
    """
    A single machine-readable reconciliation discrepancy.

    Carries full provenance: which documents and line items are involved,
    what was expected vs. actual, the computed difference, and
    a human-readable explanation. Severity is assigned by deterministic
    rules, not by the LLM.
    """
    model_config = ConfigDict(extra="ignore")

    type: DiscrepancyType = Field(
        description="Classification of the discrepancy."
    )
    severity: Severity = Field(
        description="Deterministic severity assigned by rule-based engine."
    )

    # Document provenance
    document_ids: List[str] = Field(
        default_factory=list,
        description="IDs of documents involved (e.g., PO-10045, INV-50021)."
    )
    po_line_id: Optional[str] = Field(
        default=None,
        description="PO line identifier (e.g., PO-10045-L2)."
    )
    invoice_line_id: Optional[str] = Field(
        default=None,
        description="Invoice line identifier (e.g., INV-50021-L1)."
    )
    receipt_line_id: Optional[str] = Field(
        default=None,
        description="Receipt line identifier."
    )

    # Values
    expected_value: Optional[str] = Field(
        default=None,
        description="The expected value (from the authoritative source, usually PO)."
    )
    actual_value: Optional[str] = Field(
        default=None,
        description="The actual value found (usually from Invoice or Receipt)."
    )
    difference: Optional[Decimal] = Field(
        default=None,
        description="Absolute numeric difference when applicable."
    )
    difference_percent: Optional[Decimal] = Field(
        default=None,
        description="Percentage difference when applicable."
    )

    # Additional structured details for complex discrepancies
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Arbitrary structured metadata for the discrepancy, such as "
            "charge_name and amount for UNAUTHORIZED_CHARGE."
        )
    )

    explanation: Optional[str] = Field(
        default=None,
        description="Human-readable description of the discrepancy."
    )


# ============================================================
# DOCUMENT LINKING
# ============================================================

class LinkingEvidence(BaseModel):
    """Evidence supporting the linking of documents into a transaction."""
    model_config = ConfigDict(extra="ignore")

    confidence: LinkingConfidence = Field(
        description="Confidence tier: HIGH (auto-link), MEDIUM (review), LOW (reject)."
    )
    score: float = Field(
        ge=0.0, le=1.0,
        description="Numeric confidence score from 0.0 to 1.0."
    )
    matched_identifiers: List[str] = Field(
        default_factory=list,
        description="Identifiers that matched (e.g., 'po_number', 'vendor')."
    )
    reasons: List[str] = Field(
        default_factory=list,
        description="Human-readable reasons for the confidence assessment."
    )
    candidate_details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata about the candidate match."
    )


class DocumentLinkResult(BaseModel):
    """Result of the document linking stage."""
    model_config = ConfigDict(extra="ignore")

    linked: bool = Field(
        description="Whether documents were successfully linked."
    )
    evidence: Optional[LinkingEvidence] = Field(
        default=None,
        description="Evidence supporting the link decision."
    )
    missing_documents: List[str] = Field(
        default_factory=list,
        description="Document types that are absent (e.g., 'RECEIPT', 'PURCHASE_ORDER')."
    )


# ============================================================
# LINE-ITEM MATCHING
# ============================================================

class LineItemMatch(BaseModel):
    """
    A matched pair (or triplet) of line items across PO, Invoice, and Receipts.

    Every match records the method used and confidence level, providing
    full explainability for the agent and auditors.
    """
    model_config = ConfigDict(extra="ignore")

    po_line_id: Optional[str] = Field(
        default=None,
        description="PO line identifier (e.g., PO-10045-L1)."
    )
    invoice_line_id: Optional[str] = Field(
        default=None,
        description="Invoice line identifier (e.g., INV-50021-L3)."
    )
    receipt_line_ids: List[str] = Field(
        default_factory=list,
        description="Receipt line identifiers (supports partial deliveries)."
    )

    # Match provenance
    match_method: MatchMethod = Field(
        description="How the match was determined."
    )
    match_confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence of the match (1.0 = exact, lower = fuzzy)."
    )
    match_rationale: Optional[str] = Field(
        default=None,
        description="Human-readable explanation of why these items were paired."
    )

    # Quantity fields (populated by quantity reconciler)
    ordered_quantity: Optional[Decimal] = Field(default=None)
    invoiced_quantity: Optional[Decimal] = Field(default=None)
    received_quantity: Optional[Decimal] = Field(default=None)

    # Price fields (populated by price reconciler or receipt extractor)
    ordered_unit_price: Optional[Decimal] = Field(default=None)
    invoiced_unit_price: Optional[Decimal] = Field(default=None)
    received_unit_price: Optional[Decimal] = Field(default=None)
    received_total: Optional[Decimal] = Field(default=None)
    price_difference: Optional[Decimal] = Field(default=None)
    price_difference_percent: Optional[Decimal] = Field(default=None)

    # Raw item data for reference
    po_item: Optional[Dict[str, Any]] = Field(default=None)
    invoice_item: Optional[Dict[str, Any]] = Field(default=None)
    receipt_items: List[Dict[str, Any]] = Field(default_factory=list)


# ============================================================
# RECONCILIATION CHECK (per-stage result)
# ============================================================

class ReconciliationCheck(BaseModel):
    """Result of a single reconciliation check within a stage."""
    model_config = ConfigDict(extra="ignore")

    check_name: str = Field(
        description="Name of the check (e.g., 'vendor_alignment', 'po_reference')."
    )
    stage: str = Field(
        description="Reconciliation stage (e.g., 'header', 'quantity', 'price')."
    )
    passed: bool = Field(
        description="Whether the check passed."
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured details about the check result."
    )
    message: str = Field(
        default="",
        description="Human-readable summary of the check outcome."
    )


# ============================================================
# RECEIPT RECONCILIATION TABLE ROW
# ============================================================

class ReceiptLineComparison(BaseModel):
    """A single row in the 3-way receipt reconciliation table."""
    model_config = ConfigDict(extra="ignore")

    item_description: str = Field(description="Item description.")
    po_quantity: Optional[Decimal] = Field(default=None)
    invoice_quantity: Optional[Decimal] = Field(default=None)
    received_quantity: Optional[Decimal] = Field(default=None)
    status: str = Field(
        default="MATCHED",
        description="Line status: MATCHED, SHORTAGE, OVER_DELIVERY, MISSING."
    )
    po_unit_price: Optional[Decimal] = Field(default=None)
    invoice_unit_price: Optional[Decimal] = Field(default=None)
    received_unit_price: Optional[Decimal] = Field(default=None)
    po_total: Optional[Decimal] = Field(default=None)
    invoice_total: Optional[Decimal] = Field(default=None)
    received_total: Optional[Decimal] = Field(default=None)
    price_status: str = Field(
        default="NOT_APPLICABLE",
        description="Price status: MATCHED, PRICE_MISMATCH, NOT_APPLICABLE."
    )


# ============================================================
# FINANCIAL BREAKDOWN
# ============================================================

class FinancialBreakdown(BaseModel):
    """Structured comparison of financial components across PO, Invoice, and Receipts."""
    model_config = ConfigDict(extra="ignore")

    po_subtotal: Optional[Decimal] = Field(default=None)
    invoice_subtotal: Optional[Decimal] = Field(default=None)
    receipt_subtotal: Optional[Decimal] = Field(default=None)

    po_shipping: Optional[Decimal] = Field(default=None)
    invoice_shipping: Optional[Decimal] = Field(default=None)

    po_tax: Optional[Decimal] = Field(default=None)
    invoice_tax: Optional[Decimal] = Field(default=None)

    po_discount: Optional[Decimal] = Field(default=None)
    invoice_discount: Optional[Decimal] = Field(default=None)

    po_total: Optional[Decimal] = Field(default=None)
    invoice_total: Optional[Decimal] = Field(default=None)
    receipt_total: Optional[Decimal] = Field(default=None)

    unauthorized_charges: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Charges present on the invoice but absent from the PO. "
            "Each entry contains charge_name and amount."
        )
    )


# ============================================================
# RECONCILIATION RESULT (Final Output)
# ============================================================

class ReconciliationResult(BaseModel):
    """
    The complete, machine-readable output of the reconciliation engine.

    This is the central object passed to the Investigation Agent.
    It contains all stage results, matched items, discrepancies,
    and the final deterministic status.
    """
    model_config = ConfigDict(extra="ignore")

    case_id: str = Field(
        description="Unique reconciliation case identifier (e.g., REC-000123)."
    )

    # Document identifiers
    invoice_id: Optional[str] = Field(default=None)
    purchase_order_id: Optional[str] = Field(default=None)
    receipt_ids: List[str] = Field(
        default_factory=list,
        description="Receipt/GRN identifiers (supports partial deliveries)."
    )

    # Overall status
    status: ReconciliationStatus = Field(
        description="Final reconciliation status."
    )

    # Stage results
    document_validation_checks: List[ReconciliationCheck] = Field(default_factory=list)
    document_linking: Optional[DocumentLinkResult] = Field(default=None)
    header_checks: List[ReconciliationCheck] = Field(default_factory=list)
    line_item_matches: List[LineItemMatch] = Field(default_factory=list)
    quantity_checks: List[ReconciliationCheck] = Field(default_factory=list)
    price_checks: List[ReconciliationCheck] = Field(default_factory=list)
    financial_checks: List[ReconciliationCheck] = Field(default_factory=list)
    financial_breakdown: Optional[FinancialBreakdown] = Field(default=None)
    receipt_checks: List[ReconciliationCheck] = Field(default_factory=list)
    receipt_comparison_table: List[ReceiptLineComparison] = Field(default_factory=list)

    # Aggregated discrepancies from all stages
    discrepancies: List[Discrepancy] = Field(default_factory=list)

    # Missing documents
    missing_documents: List[str] = Field(
        default_factory=list,
        description="Document types absent from the case (e.g., 'RECEIPT')."
    )

    # Human-readable summary
    summary: Optional[str] = Field(
        default=None,
        description="Generated summary of the reconciliation outcome."
    )

    # Timestamp
    reconciled_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp of when reconciliation was performed."
    )

    def has_critical_discrepancies(self) -> bool:
        """Check if any discrepancies have CRITICAL severity."""
        return any(d.severity == Severity.CRITICAL for d in self.discrepancies)

    def has_high_discrepancies(self) -> bool:
        """Check if any discrepancies have HIGH or CRITICAL severity."""
        return any(
            d.severity in (Severity.HIGH, Severity.CRITICAL)
            for d in self.discrepancies
        )

    def discrepancy_count_by_severity(self) -> Dict[str, int]:
        """Count discrepancies grouped by severity."""
        counts: Dict[str, int] = {}
        for d in self.discrepancies:
            counts[d.severity.value] = counts.get(d.severity.value, 0) + 1
        return counts

    def to_agent_summary(self) -> str:
        """Generate a structured summary for the Investigation Agent."""
        lines = [
            f"Case {self.case_id}",
            f"Status: {self.status.value}",
            f"PO: {self.purchase_order_id or 'N/A'}",
            f"Invoice: {self.invoice_id or 'N/A'}",
            f"Receipts: {', '.join(self.receipt_ids) if self.receipt_ids else 'N/A'}",
        ]
        if self.missing_documents:
            lines.append(f"Missing: {', '.join(self.missing_documents)}")
        if self.discrepancies:
            lines.append(f"\nDiscrepancies ({len(self.discrepancies)}):")
            for i, d in enumerate(self.discrepancies, 1):
                lines.append(
                    f"  {i}. [{d.severity.value}] {d.type.value}: "
                    f"{d.explanation or 'No explanation'}"
                )
        else:
            lines.append("\nNo discrepancies found.")
        return "\n".join(lines)

