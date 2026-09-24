"""
Pydantic schemas and enums for document classification and ingestion routing.
"""
from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, ConfigDict


class DocumentType(str, Enum):
    """Supported document types in the ReconAgent ingestion system."""
    INVOICE = "invoice"
    PURCHASE_ORDER = "purchase_order"
    RECEIPT = "receipt"
    UNKNOWN = "unknown"


class PipelineTarget(str, Enum):
    """Target downstream extraction pipeline for a classified document."""
    INVOICE_PIPELINE = "invoice_pipeline"
    PO_PIPELINE = "po_pipeline"
    RECEIPT_PIPELINE = "receipt_pipeline"
    MANUAL_REVIEW = "manual_review"


class ClassificationResult(BaseModel):
    """Detailed result of classifying an individual document."""
    model_config = ConfigDict(extra="ignore")

    file_name: str
    file_path: str
    document_type: DocumentType
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    tier_used: str = Field(description="Engine tier used ('local_text' or 'multimodal_vision')")
    reasoning: str = Field(description="Human-readable rationale for the classification decision")
    key_indicators: List[str] = Field(default_factory=list, description="Key features or keywords detected")
    suggested_pipeline: PipelineTarget = Field(description="Target downstream extraction pipeline")


class BatchClassificationReport(BaseModel):
    """Summary report for batch classification over a directory or list of files."""
    model_config = ConfigDict(extra="ignore")

    total_files: int
    counts: Dict[str, int] = Field(default_factory=dict)
    processing_time_seconds: float
    results: List[ClassificationResult] = Field(default_factory=list)

