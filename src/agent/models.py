"""
AI Investigation Agent Models.

Defines production-grade Pydantic schemas for evidence gathering, discrepancy findings,
agent decision actions, and the official investigation output.
All schemas are thoroughly prompt-engineered with detailed operational docstrings,
field descriptions, constraints, examples, and resilient defensive normalizers.
"""
import json
import re
from typing import List, Dict, Any, Optional, Literal, Union
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


# =============================================================================
# 1. EVIDENCE MODEL
# =============================================================================

class Evidence(BaseModel):
    """
    An authoritative, verifiable piece of forensic evidence gathered during an investigation.
    
    Serves as an immutable proof record linking a specific discrepancy to concrete data
    retrieved from enterprise source documents (Purchase Orders, Invoices, Delivery Receipts,
    Change Authorizations, Vendor History). Every finding in the investigation must be backed
    by one or more Evidence records to guarantee auditability, explainability, and legal defense.
    """
    model_config = ConfigDict(extra="ignore")

    evidence_id: str = Field(
        ...,
        description=(
            "Unique identifier for the evidence item, formatted sequentially as 'EVID-XXX' "
            "(e.g., 'EVID-001', 'EVID-002'). Must be unique across all evidence records within the case."
        ),
        examples=["EVID-001", "EVID-002"],
    )
    source_type: str = Field(
        ...,
        description=(
            "The authoritative enterprise record category where this evidence was discovered. "
            "Must be one of: 'purchase_order', 'invoice', 'receipt', 'authorization', "
            "'vendor_history', 'contract', 'receiving_dock', 'credit_memo'. "
            "Do NOT use vague classifications such as 'doc' or 'file'."
        ),
        examples=["purchase_order", "invoice", "receipt", "authorization"],
    )
    source_id: str = Field(
        ...,
        description=(
            "The specific document number or entity reference code from which the evidence was extracted "
            "(e.g., 'PO-1002-3011', 'INV-5612', 'REC-9921', 'AUTH-CHG-004'). "
            "Do not provide generic file paths; extract the exact commercial document identifier."
        ),
        examples=["PO-1002-3011", "INV-5612", "REC-9921"],
    )
    field: Optional[str] = Field(
        default=None,
        description=(
            "The exact document attribute, column, or metadata key inspected "
            "(e.g., 'unit_price', 'quantity_delivered', 'billed_quantity', 'subtotal', 'tax', "
            "'is_authorized', 'payment_terms', 'line_total'). Use 'general' or null if the evidence "
            "represents an overall document observation rather than a single specific field."
        ),
        examples=["unit_price", "quantity_delivered", "is_authorized"],
    )
    value: Optional[str] = Field(
        default=None,
        description=(
            "The exact recorded value or state discovered in the source record "
            "(e.g., '45.00', '40', 'True', 'False', 'Net 30'). "
            "If a field or document was missing on file, explicitly record 'NOT_FOUND'. "
            "Never guess, extrapolate, or invent a value that was not present in the tool response."
        ),
        examples=["45.00", "40", "True", "NOT_FOUND"],
    )
    description: str = Field(
        ...,
        description=(
            "Objective, factual observation explaining what this specific evidence proves regarding the transaction. "
            "Must state the factual finding without speculative assertions "
            "(e.g., 'PO PO-1002-3011 line 1 approved unit price is $45.00')."
        ),
        examples=["PO PO-1002-3011 line 'UltraWhite A4 Copy Paper' approved unit price is $45.00 (authorized qty: 50)."],
    )

    @field_validator("evidence_id", mode="before")
    @classmethod
    def normalize_evidence_id(cls, v: Any) -> str:
        if v is None:
            return "EVID-000"
        s = str(v).strip()
        if re.match(r"^\d+$", s):
            return f"EVID-{int(s):03d}"
        return s

    @field_validator("source_type", mode="before")
    @classmethod
    def normalize_source_type(cls, v: Any) -> str:
        if isinstance(v, str):
            clean = v.strip().lower()
            alias_map = {
                "po": "purchase_order",
                "inv": "invoice",
                "rcpt": "receipt",
                "auth": "authorization",
                "vendor": "vendor_history",
            }
            return alias_map.get(clean, clean)
        return str(v).lower()

    @field_validator("value", mode="before")
    @classmethod
    def normalize_value(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return str(v).strip()


# =============================================================================
# 2. FINDING MODEL
# =============================================================================

class Finding(BaseModel):
    """
    Synthesized forensic finding explaining the root cause of an investigated discrepancy.
    
    Isolates why a specific commercial discrepancy occurred (e.g., physical dock delivery shortage,
    unapproved vendor price escalation, mathematical calculation error) and maps it directly
    to the supporting Evidence IDs that substantiate the finding.
    """
    model_config = ConfigDict(extra="ignore")

    finding_id: str = Field(
        ...,
        description=(
            "Unique identifier for the synthesized finding, formatted sequentially as 'FIND-XXX' "
            "(e.g., 'FIND-001', 'FIND-002'). Must be unique within the case."
        ),
        examples=["FIND-001", "FIND-002"],
    )
    discrepancy_type: str = Field(
        ...,
        description=(
            "The standardized discrepancy category being addressed. "
            "Examples include: 'PRICE_MISMATCH', 'QUANTITY_SHORTAGE', 'INVOICE_QUANTITY_EXCEEDS_RECEIVED', "
            "'UNAUTHORIZED_CHARGE', 'TAX_VARIANCE', 'SUBTOTAL_MISMATCH', 'MATH_ERROR', "
            "'DOCUMENT_LINK_MISMATCH', 'MISSING_DOCUMENT', 'ITEM_SUBSTITUTION', 'DUPLICATE_INVOICE'. "
            "Preserve standard uppercase taxonomy."
        ),
        examples=["PRICE_MISMATCH", "INVOICE_QUANTITY_EXCEEDS_RECEIVED", "UNAUTHORIZED_CHARGE"],
    )
    explanation: str = Field(
        ...,
        description=(
            "Detailed, objective explanation of the investigative conclusion and commercial root cause. "
            "Must clearly state: (1) what discrepancy was found, (2) why it happened based on retrieved records, "
            "and (3) whether it was formally authorized. Avoid vague assertions like 'issue verified'."
        ),
        examples=[
            "Physical delivery shortage confirmed by receiving dock records (40 units delivered vs 50 billed). "
            "Vendor invoiced for ordered quantity prior to full fulfillment without partial shipment credit."
        ],
    )
    supporting_evidence_ids: List[str] = Field(
        default_factory=list,
        description=(
            "Array of Evidence IDs that directly substantiate and prove this finding "
            "(e.g., ['EVID-001', 'EVID-003', 'EVID-005']). Must reference valid Evidence records "
            "present in the case evidence repository."
        ),
        examples=[["EVID-001", "EVID-002"]],
    )
    confidence: str = Field(
        default="HIGH",
        description=(
            "Confidence level in this finding based on the quality and completeness of retrieved documentary evidence. "
            "Must be one of: 'HIGH' (fully corroborated by primary source records), "
            "'MEDIUM' (partial records available or circumstantial evidence), "
            "'LOW' (records missing, contradictory, or unverified)."
        ),
        examples=["HIGH", "MEDIUM", "LOW"],
    )

    @field_validator("finding_id", mode="before")
    @classmethod
    def normalize_finding_id(cls, v: Any) -> str:
        if v is None:
            return "FIND-000"
        s = str(v).strip()
        if re.match(r"^\d+$", s):
            return f"FIND-{int(s):03d}"
        return s

    @field_validator("discrepancy_type", mode="before")
    @classmethod
    def normalize_discrepancy_type(cls, v: Any) -> str:
        if isinstance(v, str):
            # Strip DiscrepancyType. prefix if present
            s = v.strip()
            if s.startswith("DiscrepancyType."):
                s = s.replace("DiscrepancyType.", "")
            return s.upper()
        return str(v).upper()

    @field_validator("supporting_evidence_ids", mode="before")
    @classmethod
    def normalize_evidence_ids(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, str):
            # Handles comma/space-separated string or single string
            parts = [p.strip() for p in re.split(r"[,;]+", v) if p.strip()]
            return parts
        if isinstance(v, (list, tuple)):
            return [str(item).strip() for item in v if item]
        return [str(v)]

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, v: Any) -> str:
        if isinstance(v, str):
            clean = v.strip().upper()
            if clean in ("HIGH", "MEDIUM", "LOW"):
                return clean
        return "HIGH"


# =============================================================================
# 3. INVESTIGATION RESULT MODEL
# =============================================================================

class InvestigationResult(BaseModel):
    """
    Authoritative, audit-ready final outcome of an autonomous AI forensic investigation.
    
    Packages all synthesized findings, gathered evidence provenance, the actionable
    settlement recommendation, and human specialist review requirements into an
    immutable decision artifact for financial enterprise settlement.
    """
    model_config = ConfigDict(extra="ignore")

    case_id: str = Field(
        ...,
        description=(
            "Unique case or transaction identifier exactly matching the transaction under audit "
            "(e.g., 'PO-1002-3011', 'TRX_1789455825_002', 'CASE-0001')."
        ),
        examples=["PO-1002-3011", "TRX_1789455825_002"],
    )
    findings: List[Finding] = Field(
        default_factory=list,
        description=(
            "List of all verified investigative findings. Each finding must address an identified discrepancy "
            "and cite supporting evidence IDs."
        ),
    )
    evidence: List[Evidence] = Field(
        default_factory=list,
        description=(
            "Complete repository of all evidence records gathered across tool executions during the investigation, "
            "providing transparent provenance and auditability."
        ),
    )
    recommendation: str = Field(
        ...,
        description=(
            "Prescribed commercial settlement action. Must be one of the following authoritative action codes:\n"
            "- 'APPROVE_PAYMENT': All discrepancies verified and authorized, or matched cleanly within policy tolerance.\n"
            "- 'REQUEST_CREDIT_MEMO': Vendor billed for unreceived items, unapproved price increases, or duplicate fees requiring credit deduction before payment.\n"
            "- 'REJECT_INVOICE': Severe compliance violation, duplicate billing, fraudulent submission, or unresolvable mismatch.\n"
            "- 'ESCALATE_TO_BUYER': Missing source records, ambiguous commercial terms, or procurement buyer confirmation needed.\n"
            "- 'HOLD_FOR_RECEIPT': Invoiced items have not yet arrived at the dock; payment paused until delivery confirmation.\n"
            "- 'CANCEL_DUPLICATE': Redundant duplicate invoice submission identified."
        ),
        examples=["APPROVE_PAYMENT", "REQUEST_CREDIT_MEMO", "REJECT_INVOICE", "ESCALATE_TO_BUYER"],
    )
    confidence: str = Field(
        default="HIGH",
        description=(
            "Overall confidence rating for the recommended settlement action: "
            "'HIGH' (complete documentary trail), 'MEDIUM' (acceptable certainty but partial documentation), "
            "'LOW' (insufficient or conflicting records)."
        ),
        examples=["HIGH", "MEDIUM", "LOW"],
    )
    requires_human_review: bool = Field(
        default=False,
        description=(
            "True if an Accounts Payable specialist or Procurement buyer must review and sign off on this case "
            "before ERP release. Must be True whenever discrepancies are present or recommendation is not APPROVE_PAYMENT."
        ),
        examples=[True, False],
    )
    final_summary: Optional[str] = Field(
        default=None,
        description="Executive narrative summary or root-cause explanation for the investigation outcome.",
    )

    @field_validator("recommendation", mode="before")
    @classmethod
    def normalize_recommendation(cls, v: Any) -> str:
        if isinstance(v, str):
            clean = v.strip().upper()
            synonyms = {
                "PAYMENT_ELIGIBLE": "APPROVE_PAYMENT",
                "APPROVE": "APPROVE_PAYMENT",
                "PAY": "APPROVE_PAYMENT",
                "CREDIT_MEMO": "REQUEST_CREDIT_MEMO",
                "REQUEST_CREDIT": "REQUEST_CREDIT_MEMO",
                "REJECT": "REJECT_INVOICE",
                "ESCALATE": "ESCALATE_TO_BUYER",
                "BUYER_REVIEW": "ESCALATE_TO_BUYER",
                "HOLD": "HOLD_FOR_RECEIPT",
                "DUPLICATE": "CANCEL_DUPLICATE",
            }
            return synonyms.get(clean, clean)
        return str(v).upper()

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, v: Any) -> str:
        if isinstance(v, str):
            clean = v.strip().upper()
            if clean in ("HIGH", "MEDIUM", "LOW"):
                return clean
        return "HIGH"

    @field_validator("requires_human_review", mode="before")
    @classmethod
    def normalize_human_review(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "y", "required")
        return bool(v)

    def to_executive_summary(self) -> str:
        """Renders an executive briefing of the investigation outcome."""
        lines = [
            f"=== INVESTIGATION REPORT: {self.case_id} ===",
            f"Recommendation: {self.recommendation} (Confidence: {self.confidence})",
            f"Human Review Required: {'YES' if self.requires_human_review else 'NO'}",
        ]
        if not self.findings:
            if self.recommendation == "APPROVE_PAYMENT":
                lines.extend([
                    "",
                    "Outcome: Clean 3-way match verified. All purchase order line rates, quantities, and invoiced amounts match with zero discrepancies.",
                    "Settlement: Authorized for automated ERP payment release.",
                ])
            else:
                lines.extend([
                    "",
                    f"Outcome: Investigation concluded with recommendation {self.recommendation}.",
                    "No explicit line discrepancy findings identified.",
                ])
        else:
            lines.append("")
            lines.append(f"Findings ({len(self.findings)}):")
            for f in self.findings:
                evidence_refs = ", ".join(f.supporting_evidence_ids) if f.supporting_evidence_ids else "None"
                lines.append(f"  [{f.finding_id}] {f.discrepancy_type} ({f.confidence} confidence):")
                lines.append(f"    Explanation: {f.explanation}")
                lines.append(f"    Evidence: {evidence_refs}")

        if self.evidence:
            lines.append("")
            lines.append(f"Evidence Records ({len(self.evidence)}):")
            for e in self.evidence:
                val_str = f" = {e.value}" if e.value is not None else ""
                lines.append(f"  [{e.evidence_id}] {e.source_type} ({e.source_id}): {e.field or 'general'}{val_str}")
                lines.append(f"    Note: {e.description}")

        return "\n".join(lines)


# =============================================================================
# 4. AGENT ACTION MODEL
# =============================================================================

ALLOWED_AGENT_ACTIONS = {"investigate", "finish"}
ALLOWED_INVESTIGATION_TOOLS = {
    "get_purchase_order",
    "get_invoice",
    "get_receipt",
    "check_authorization",
    "get_vendor_history",
    "find_similar_invoices",
}


class AgentAction(BaseModel):
    """
    The atomic operational decision emitted by the autonomous AI Investigation Agent at each reasoning step.
    
    Enforces strict operational boundaries:
    1. 'investigate': Execute a purposeful, registered tool to retrieve missing facts for an unresolved discrepancy.
    2. 'finish': Conclude the investigation when sufficient evidence is established or tools are exhausted.
    """
    model_config = ConfigDict(extra="ignore")

    action: Literal["investigate", "finish"] = Field(
        ...,
        description=(
            "The operational next step for the investigation agent. "
            "Must be strictly either:\n"
            "- 'investigate': Choose this when unresolved discrepancies require additional factual verification from enterprise tools.\n"
            "- 'finish': Choose this when all discrepancies are substantiated by evidence, or all relevant tools have been exhausted."
        ),
        examples=["investigate", "finish"],
    )
    reason: str = Field(
        ...,
        description=(
            "Clear, concise justification explaining why this specific action was selected. "
            "If 'investigate', specify the exact hypothesis or fact being checked (e.g., 'Verify delivered quantity on Receipt REC-9921'). "
            "If 'finish', summarize the conclusive findings that allow the investigation to close."
        ),
        examples=[
            "Need to inspect physical delivery confirmation and delivered quantities in Receipt REC-9921.",
            "Completed physical delivery receiving investigation across PO, invoice, and delivery receipts."
        ],
    )
    tool: Optional[str] = Field(
        default=None,
        description=(
            "The registered investigation tool to call. Required if action is 'investigate'; must be null if action is 'finish'. "
            "Must be one of:\n"
            "- 'get_purchase_order': Retrieves authorized lines, quantities, and prices for a PO.\n"
            "- 'get_invoice': Retrieves billed lines, charges, tax, and shipping on an invoice.\n"
            "- 'get_receipt': Retrieves dock delivery records and quantities delivered.\n"
            "- 'check_authorization': Checks whether formal price/quantity change orders were approved.\n"
            "- 'get_vendor_history': Inspects past historical invoice unit prices for this vendor.\n"
            "- 'find_similar_invoices': Searches past invoices for identical or similar products."
        ),
        examples=["get_purchase_order", "get_invoice", "get_receipt", "check_authorization"],
    )
    arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Dictionary of keyword arguments passed to the chosen tool. Required when action is 'investigate'; empty `{}` when action is 'finish'. "
            "Tool argument signatures:\n"
            "- `get_purchase_order`: `{'po_id': '<PO_NUMBER>'}`\n"
            "- `get_invoice`: `{'invoice_id': '<INVOICE_NUMBER>'}`\n"
            "- `get_receipt`: `{'receipt_id': '<RECEIPT_NUMBER>'}`\n"
            "- `check_authorization`: `{'po_id': '<PO_NUMBER>', 'discrepancy_type': '<TYPE>'}`\n"
            "- `get_vendor_history`: `{'vendor_id': '<VENDOR_NAME>'}`\n"
            "- `find_similar_invoices`: `{'vendor_id': '<VENDOR_NAME>', 'item_description': '<DESC>'}`"
        ),
        examples=[{"po_id": "PO-1002-3011"}, {"invoice_id": "INV-5612"}, {"receipt_id": "REC-9921"}],
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_input_dict(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Tolerate LLM output variation: reasoning -> reason
            if "reason" not in data and "reasoning" in data:
                data["reason"] = data["reasoning"]
            # Tolerate LLM output variation: parameters / args / params -> arguments
            for alt_key in ("parameters", "params", "args", "tool_input"):
                if "arguments" not in data and alt_key in data:
                    data["arguments"] = data[alt_key]
            # If arguments was emitted as a serialized JSON string, parse it
            if isinstance(data.get("arguments"), str):
                try:
                    data["arguments"] = json.loads(data["arguments"])
                except Exception:
                    data["arguments"] = {}
            # If action is finish, guarantee tool is None and arguments is empty
            act = str(data.get("action", "")).strip().lower()
            if act == "finish":
                data["tool"] = None
                if not data.get("arguments"):
                    data["arguments"] = {}
        return data

    @field_validator("action", mode="before")
    @classmethod
    def normalize_action(cls, v: Any) -> str:
        if isinstance(v, str):
            clean = v.strip().lower()
            if clean in ALLOWED_AGENT_ACTIONS:
                return clean
            raise ValueError(
                f"Invalid action '{v}'. Permitted actions are strictly: {sorted(ALLOWED_AGENT_ACTIONS)}"
            )
        return v

    @field_validator("tool", mode="before")
    @classmethod
    def normalize_tool(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            clean = v.strip().lower()
            if clean in ("none", "null", ""):
                return None
            return clean
        return str(v)
