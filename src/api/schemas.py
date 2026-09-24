"""
Pydantic v2 schemas for ReconAgent FastAPI REST layer.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field


# =============================================================================
# 1. HEALTH & SYSTEM SCHEMAS
# =============================================================================
class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str = "1.0.0"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    database_connected: bool = True
    total_investigations: int = 0
    review_queue_pending: int = 0


class SystemInfoResponse(BaseModel):
    system_name: str = "ReconAgent — AI-Powered Invoice Reconciliation & Investigation System"
    version: str = "1.0.0"
    supported_models: List[str] = Field(
        default_factory=lambda: [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
            "gemini-3-flash",
            "gemini-2.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite",
        ]
    )
    supported_document_types: List[str] = Field(
        default_factory=lambda: ["PURCHASE_ORDER", "INVOICE", "RECEIPT"]
    )
    supported_file_extensions: List[str] = Field(
        default_factory=lambda: [".txt", ".pdf", ".png", ".jpg", ".jpeg", ".tiff"]
    )


# =============================================================================
# 2. DOCUMENT INGESTION & EXTRACTION SCHEMAS
# =============================================================================
class DocumentItemSchema(BaseModel):
    file_name: str
    file_path: Optional[str] = None
    document_type: str
    confidence: float = 1.0
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    validation_status: str = "VALID"
    validation_errors: List[str] = Field(default_factory=list)


class DocumentUploadResponse(BaseModel):
    total_uploaded: int
    documents: List[DocumentItemSchema]


class IngestDirectoryRequest(BaseModel):
    directory_path: str
    file_pattern: str = "*.*"


class SupportedTypesResponse(BaseModel):
    supported_types: List[str]
    supported_extensions: List[str]


class DocumentContentResponse(BaseModel):
    file_name: str
    file_path: str
    content: str
    file_size_bytes: int = 0
    is_binary: bool = False
    document_type: Optional[str] = None


# =============================================================================
# 3. CASES & RECONCILIATION SCHEMAS
# =============================================================================
class ReconcileTransactionRequest(BaseModel):
    case_id: Optional[str] = None
    po_data: Optional[Dict[str, Any]] = None
    invoice_data: Optional[Dict[str, Any]] = None
    receipt_data_list: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


class CaseSummary(BaseModel):
    case_id: str
    vendor_name: Optional[str] = None
    po_number: Optional[str] = None
    invoice_number: Optional[str] = None
    receipt_numbers: List[str] = Field(default_factory=list)
    po_file: Optional[str] = None
    invoice_file: Optional[str] = None
    receipt_files: List[str] = Field(default_factory=list)
    source_files: List[str] = Field(default_factory=list)
    status: str
    recommendation: str
    confidence: str = "HIGH"
    requires_human_review: bool = False
    discrepancy_count: int = 0
    duration_ms: float = 0.0
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


class CaseListResponse(BaseModel):
    total: int
    cases: List[CaseSummary]


class CaseDetailResponse(BaseModel):
    case_id: str
    vendor_name: Optional[str] = None
    po_number: Optional[str] = None
    invoice_number: Optional[str] = None
    receipt_numbers: List[str] = Field(default_factory=list)
    po_file: Optional[str] = None
    invoice_file: Optional[str] = None
    receipt_files: List[str] = Field(default_factory=list)
    source_files: List[str] = Field(default_factory=list)
    status: str
    recommendation: str = "UNKNOWN"
    confidence: str = "HIGH"
    requires_human_review: bool = False
    discrepancy_count: int = 0
    discrepancies: List[Dict[str, Any]] = Field(default_factory=list)
    reconciliation_result: Optional[Dict[str, Any]] = None
    investigation_result: Optional[Dict[str, Any]] = None
    duration_ms: float = 0.0
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


class BatchReconcileRequest(BaseModel):
    directory_path: Optional[str] = None
    file_pattern: str = "*.txt"
    case_id_override: Optional[str] = None


class BatchReconcileResponse(BaseModel):
    total_documents: int
    total_transactions: int
    matched_clean: int
    discrepancies_flagged: int
    investigated_by_agent: int
    sent_to_review_queue: int
    overall_duration_ms: float
    transactions: List[CaseDetailResponse]


# =============================================================================
# 4. INVESTIGATION SCHEMAS
# =============================================================================
class FindingSchema(BaseModel):
    finding_id: str
    discrepancy_type: str
    explanation: str
    confidence: str = "HIGH"
    supporting_evidence_ids: List[str] = Field(default_factory=list)


class EvidenceSchema(BaseModel):
    evidence_id: str
    source_type: str
    source_id: str
    field: Optional[str] = None
    value: Optional[str] = None
    description: str = ""


class EventSchema(BaseModel):
    id: str
    event_type: str
    tool_name: Optional[str] = None
    arguments: Any = None
    result: Any = None
    created_at: str


class InvestigationSummary(BaseModel):
    id: str
    case_id: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    recommendation: Optional[str] = None
    confidence: Optional[str] = None
    requires_human_review: bool = False


class InvestigationListResponse(BaseModel):
    total: int
    investigations: List[InvestigationSummary]


class InvestigationDetailResponse(BaseModel):
    id: str
    case_id: str
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    recommendation: Optional[str] = None
    confidence: Optional[str] = None
    requires_human_review: bool = False
    final_summary: Optional[str] = None
    findings: List[FindingSchema] = Field(default_factory=list)
    evidence: List[EvidenceSchema] = Field(default_factory=list)
    events: List[EventSchema] = Field(default_factory=list)
    human_decision: Optional[Dict[str, Any]] = None


class RunInvestigationRequest(BaseModel):
    case_id: str


# =============================================================================
# 5. REVIEW QUEUE SCHEMAS
# =============================================================================
class ReviewQueueMetricsResponse(BaseModel):
    total_count: int
    pending_count: int
    auto_approved_count: int
    approved_count: int
    overridden_count: int


class ReviewItemResponse(BaseModel):
    case_id: str
    discrepancies: List[Dict[str, Any]] = Field(default_factory=list)
    findings: List[FindingSchema] = Field(default_factory=list)
    evidence: List[EvidenceSchema] = Field(default_factory=list)
    investigation_steps: List[Dict[str, Any]] = Field(default_factory=list)
    agent_recommendation: str
    agent_confidence: str
    human_status: str
    human_decision: Optional[str] = None
    reviewer_notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    created_at: str
    rendered_briefing: Optional[str] = None


class ReviewQueueListResponse(BaseModel):
    metrics: ReviewQueueMetricsResponse
    total: int
    items: List[ReviewItemResponse]


class ReviewDecisionRequest(BaseModel):
    decision: str = Field(
        ...,
        description="Business decision (e.g. APPROVE, OVERRIDE, REJECT, ESCALATE, APPROVE_PAYMENT, REQUEST_CREDIT_MEMO, REJECT_INVOICE)",
    )
    reviewer_id: str = Field(..., description="Unique ID or username of the reviewer")
    notes: str = Field(..., description="Audit rationale explaining the decision")


class ReviewDecisionResponse(BaseModel):
    success: bool
    message: str
    item: ReviewItemResponse


class DecisionActionRequest(BaseModel):
    reviewer_id: str = Field(default="human_specialist", description="Unique ID or username of reviewer")
    notes: str = Field(default="", description="Audit rationale or review notes")


