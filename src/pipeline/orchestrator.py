"""
Master Orchestration Pipeline.

Coordinates the end-to-end assembly line across the system:
                 ORCHESTRATOR
                      │
                      ▼
              "Get the documents"
                      │
                      ▼
                 CLASSIFIER
                      │
                      ▼
              "What are these?"
                      │
                      ▼
                 EXTRACTOR
                      │
                      ▼
              "Get structured data"
                      │
                      ▼
                 VALIDATOR
                      │
                      ▼
              "Is the data/math valid?"
                      │
                      ▼
              RECONCILIATION
                      │
                      ▼
              "Any problems?"
                    /   \
                  NO     YES
                  │       │
                  ▼       ▼
              MATCHED    AGENT
                          │
                          ▼
                     INVESTIGATION
                          │
                          ▼
                       FINDING
                          │
                          ▼
                    RECOMMENDATION
                          │
                          ▼
                     REVIEW QUEUE

The orchestrator manages data handoffs between components without duplicating business logic.
"""
import os
import sys
import time
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from pydantic import BaseModel, Field

# Ensure src/ and project root are dynamically in sys.path for direct terminal execution
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 1. Document Ingestion / Classification
from ingestion import IngestedDocument, ingest_document, classify_document
from schemas.document_classification import DocumentType

# 2. Unified Extraction Boundary
from extraction import extract_document


# 3. Deterministic Validation
from validation import (
    verify_invoice_math,
    verify_purchase_order_math,
    verify_receipt_math,
)

# 4. Multi-Stage 3-Way Reconciliation
from reconciliation.pipeline import reconcile_transaction
from schemas.reconciliation import (
    ReconciliationResult,
    ReconciliationStatus,
    Discrepancy,
    DiscrepancyType,
    Severity,
    LinkingConfidence,
)
from reconciliation.document_linker import evaluate_link, normalize_vendor, normalize_po_number

# 5. Autonomous AI Investigation Agent & Governance
from agent.graph import run_investigation, MAX_TOOL_CALLS
from agent.tools.registry import AgentDataStore
from agent.db import InvestigationDatabase
from agent.review_queue import ReviewQueueManager, get_review_queue
from agent.logging import AgentLogger, get_agent_logger
from agent.models import InvestigationResult, Finding, Evidence

logger = logging.getLogger("MasterOrchestrator")


class DocumentItem(BaseModel):
    """Normalized representation of an ingested document."""
    file_path: str
    document_type: str
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    validation_status: str = "VALID"
    validation_errors: List[str] = Field(default_factory=list)


class TransactionResult(BaseModel):
    """Authoritative outcome of an end-to-end transaction pipeline execution."""
    case_id: str
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
    discrepancies: List[Dict[str, Any]] = Field(default_factory=list)
    reconciliation_result: Optional[Dict[str, Any]] = None
    investigation_result: Optional[Dict[str, Any]] = None
    duration_ms: float = 0.0


class OrchestrationReport(BaseModel):
    """Aggregate report across a batch of processed documents/transactions."""
    total_documents: int = 0
    total_transactions: int = 0
    matched_clean: int = 0
    discrepancies_flagged: int = 0
    investigated_by_agent: int = 0
    sent_to_review_queue: int = 0
    transactions: List[TransactionResult] = Field(default_factory=list)
    overall_duration_ms: float = 0.0


def _format_plain_math_error(doc_id: str, doc_label: str, d: Discrepancy) -> str:
    """Formats mathematical errors into short, clear plain English for non-technical users."""
    details = d.details or {}
    resolved = details.get("resolved_totals") or details
    calc_total = resolved.get("calculated_grand_total") or resolved.get("calculated_total")
    rep_total = resolved.get("reported_grand_total") or resolved.get("reported_total")

    if calc_total is not None and rep_total is not None:
        try:
            c_val = float(calc_total)
            r_val = float(rep_total)
            diff = abs(c_val - r_val)
            if diff > 0.001:
                return (
                    f"{doc_label} {doc_id} has a ${diff:,.2f} calculation error: "
                    f"items, tax, and shipping equal ${c_val:,.2f}, but the printed total says ${r_val:,.2f}."
                )
        except Exception:
            pass

    line_audits = details.get("line_item_audit") or []
    for la in line_audits:
        if not la.get("is_valid") and la.get("error_note"):
            desc = la.get("description") or la.get("item_code") or "item"
            err = la.get("error_note", "")
            err_clean = err.replace("Line total discrepancy: calculated", "calculated $").replace("vs reported", "vs printed on document $")
            return f"{doc_label} {doc_id} item '{desc}' arithmetic mismatch: {err_clean}."

    rep_subtotal = resolved.get("reported_subtotal")
    sum_lines = resolved.get("sum_line_totals")
    if rep_subtotal is not None and sum_lines is not None:
        try:
            s_lines = float(sum_lines)
            s_rep = float(rep_subtotal)
            diff = abs(s_lines - s_rep)
            if diff > 0.001:
                return (
                    f"{doc_label} {doc_id} subtotal error: line items add up to ${s_lines:,.2f}, "
                    f"but printed subtotal is ${s_rep:,.2f} (${diff:,.2f} difference)."
                )
        except Exception:
            pass

    clean_msg = (d.explanation or "Math discrepancy detected on document.")
    clean_msg = clean_msg.replace("internal integrity discrepancy:", "math error:")
    clean_msg = clean_msg.replace("internal math discrepancy:", "math error:")
    clean_msg = clean_msg.replace("Grand total discrepancy:", "printed total does not match calculation:")
    return f"{doc_label} {doc_id}: {clean_msg.strip()}"


class MasterOrchestrator:
    """
    Central pipeline coordinator connecting Ingestion, Extraction, Validation,
    Reconciliation, AI Agent Investigation, SQLite Storage, and the Review Queue.
    """
    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        gemini_client: Optional[Any] = None,
        max_tool_calls: int = MAX_TOOL_CALLS,
        agent_logger: Optional[AgentLogger] = None,
        review_queue: Optional[ReviewQueueManager] = None,
    ):
        if db_path is False:
            self.db = None
        else:
            self.db = InvestigationDatabase(db_path) if db_path else InvestigationDatabase()
        self.client = gemini_client
        self.max_tool_calls = max_tool_calls
        self.agent_logger = agent_logger or get_agent_logger()
        self.review_queue = review_queue or get_review_queue()

    def close(self):
        """Releases underlying resources and database connections."""
        if self.db:
            self.db.close()

    # =========================================================================
    # SINGLE TRANSACTION EXECUTION
    # =========================================================================
    def process_transaction(
        self,
        po_data: Optional[Dict[str, Any]] = None,
        invoice_data: Optional[Dict[str, Any]] = None,
        receipt_data_list: Optional[List[Dict[str, Any]]] = None,
        case_id: Optional[str] = None,
    ) -> TransactionResult:
        """
        Executes stages 4 through 7 for a single transaction set:
          1. 3-Way Reconciliation
          2. Branch on Discrepancies:
             - If 0 discrepancies -> MATCHED -> Auto-approve
             - If discrepancies -> LangGraph AI Agent Investigation -> Review Queue
          3. Persistence to SQLite and Review Queue
        """
        t_start = time.perf_counter()
        active_case_id = (
            case_id
            or (invoice_data or {}).get("invoice_number")
            or (po_data or {}).get("purchase_order_number")
            or f"CASE-{int(time.time() * 1000)}"
        )

        receipts = receipt_data_list or []

        # ---------------------------------------------------------------------
        # STAGE 4: 3-WAY RECONCILIATION
        # ---------------------------------------------------------------------
        logger.info(f"[Orchestrator] Running 3-Way Reconciliation for case {active_case_id}...")
        recon_res: ReconciliationResult = reconcile_transaction(
            po_data=po_data,
            invoice_data=invoice_data,
            receipt_data_list=receipts,
            case_id=active_case_id,
            check_duplicates=False,
        )

        discrepancies_list = [d.model_dump() for d in recon_res.discrepancies]
        discrepancy_count = len(discrepancies_list)

        # A case is only cleanly matched if no discrepancies exist, status is MATCHED, and no documents are missing
        is_clean_match = (
            recon_res.status in (ReconciliationStatus.MATCHED, ReconciliationStatus.MATCHED_WITH_TOLERANCE)
            and discrepancy_count == 0
            and not getattr(recon_res, "missing_documents", None)
        )

        if not is_clean_match and discrepancy_count == 0 and getattr(recon_res, "missing_documents", None):
            disc_type = (
                DiscrepancyType.DOCUMENT_LINK_MISMATCH
                if "PURCHASE_ORDER" in recon_res.missing_documents
                else DiscrepancyType.MISSING_DOCUMENT
            )
            missing_disc = Discrepancy(
                type=disc_type,
                severity=Severity.CRITICAL,
                explanation=f"Missing required documentation: {', '.join(recon_res.missing_documents)}",
                details={"missing_documents": recon_res.missing_documents},
            )
            recon_res.discrepancies.append(missing_disc)
            discrepancies_list = [d.model_dump() for d in recon_res.discrepancies]
            discrepancy_count = len(discrepancies_list)

        # Extract document numbers for direct file traceability
        po_num = (po_data.get("purchase_order_number") or po_data.get("po_number")) if po_data else None
        if not po_num and invoice_data:
            po_num = invoice_data.get("purchase_order_number") or invoice_data.get("po_number")
        inv_num = invoice_data.get("invoice_number") if invoice_data else None
        rcpt_nums = [
            (r.get("receipt_number") or r.get("delivery_receipt_number"))
            for r in receipts
            if (r.get("receipt_number") or r.get("delivery_receipt_number"))
        ]

        # Extract file names for direct file traceability
        po_file = Path(po_data.get("_source_file")).name if (po_data and po_data.get("_source_file")) else None
        inv_file = Path(invoice_data.get("_source_file")).name if (invoice_data and invoice_data.get("_source_file")) else None
        rcpt_files = [
            Path(r.get("_source_file")).name
            for r in receipts
            if (r and r.get("_source_file"))
        ]
        all_files = []
        if po_file and po_file not in all_files:
            all_files.append(po_file)
        if inv_file and inv_file not in all_files:
            all_files.append(inv_file)
        for rf in rcpt_files:
            if rf and rf not in all_files:
                all_files.append(rf)

        vendor_name = (
            (po_data or {}).get("vendor_name")
            or (invoice_data or {}).get("vendor_name")
            or (po_data or {}).get("vendor")
            or (invoice_data or {}).get("vendor")
            or None
        )

        # ---------------------------------------------------------------------
        # STAGE 5: BRANCHING LOGIC
        # ---------------------------------------------------------------------
        if is_clean_match:
            # NO PROBLEMS -> MATCHED
            logger.info(f"[Orchestrator] Case {active_case_id}: MATCHED (0 discrepancies). Auto-approving payment.")
            recommendation = "APPROVE_PAYMENT"
            confidence = "HIGH"
            requires_human_review = False
            inv_result_dict = None

            # Enqueue auto-approved event in review queue
            self.review_queue.enqueue(
                case_id=active_case_id,
                discrepancy_count=0,
                recommendation=recommendation,
                confidence=confidence,
                requires_human_review=False,
                metadata={"status": "AUTO_APPROVED", "source": "RECONCILIATION_MATCHED"},
            )

            # Persist to database if available
            if self.db:
                dummy_inv_res = InvestigationResult(
                    case_id=active_case_id,
                    findings=[],
                    evidence=[],
                    recommendation=recommendation,
                    confidence=confidence,
                    requires_human_review=False,
                )
                clean_state = {
                    "case_id": active_case_id,
                    "reconciliation_result": recon_res.model_dump(),
                    "discrepancies": [],
                    "evidence": [],
                    "findings": [],
                    "tool_calls": [],
                    "status": "MATCHED",
                    "po_file": po_file,
                    "invoice_file": inv_file,
                    "receipt_files": rcpt_files,
                    "source_files": all_files,
                    "vendor_name": vendor_name,
                    "po_number": po_num,
                    "invoice_number": inv_num,
                    "receipt_numbers": rcpt_nums,
                }
                self.db.save_investigation(
                    state=clean_state,
                    result=dummy_inv_res,
                    po_file=po_file,
                    invoice_file=inv_file,
                    receipt_files=rcpt_files,
                    source_files=all_files,
                    vendor_name=vendor_name,
                    po_number=po_num,
                    invoice_number=inv_num,
                    receipt_numbers=rcpt_nums,
                    reconciliation_result=recon_res.model_dump(),
                )

        elif any(
            d.type in (DiscrepancyType.CALCULATION_ERROR, DiscrepancyType.INTERNAL_MATH_ERROR)
            for d in recon_res.discrepancies
        ):
            # INTERNAL VALIDATION FAILED -> DO NOT START AGENT INVESTIGATION
            logger.warning(
                f"[Orchestrator] Case {active_case_id}: Internal document validation failed. "
                f"Bypassing AI agent investigation loop; generating immediate rejection report."
            )
            val_findings = []
            val_evidence = []
            val_errors = []

            for idx, d in enumerate(recon_res.discrepancies, start=1):
                if d.type in (DiscrepancyType.CALCULATION_ERROR, DiscrepancyType.INTERNAL_MATH_ERROR):
                    doc_id = d.document_ids[0] if d.document_ids else "Document"
                    doc_lower = doc_id.lower()
                    if "po" in doc_lower or "purchase" in doc_lower:
                        stype = "purchase_order"
                        doc_label = "Purchase Order"
                    elif "rec" in doc_lower or "trx" in doc_lower or "slip" in doc_lower or "receipt" in doc_lower or "dr" in doc_lower:
                        stype = "receipt"
                        doc_label = "Delivery Receipt"
                    else:
                        stype = "invoice"
                        doc_label = "Invoice"

                    clean_reason = _format_plain_math_error(doc_id, doc_label, d)
                    val_errors.append(clean_reason)
                    ev_id = f"EVID-{idx:03d}"
                    f_id = f"FIND-{idx:03d}"

                    # Extract human-friendly audit evidence
                    audit_field = "document_math"
                    audit_val = "Arithmetic Error"
                    line_audits = (d.details or {}).get("line_item_audit") or []
                    failed_items = [la for la in line_audits if not la.get("is_valid")]

                    if failed_items:
                        first_fail = failed_items[0]
                        rep_val = first_fail.get("reported_line_total")
                        calc_val = first_fail.get("calculated_line_total")
                        item_desc = first_fail.get("description") or "Item"
                        audit_field = f"Line Math: {item_desc}"
                        audit_val = f"Printed ${rep_val} vs Calculated ${calc_val}"
                    else:
                        resolved = (d.details or {}).get("resolved_totals") or {}
                        sum_lines = resolved.get("sum_line_totals")
                        rep_sub = resolved.get("reported_subtotal")
                        if sum_lines is not None and rep_sub is not None:
                            audit_field = "Document Subtotal"
                            audit_val = f"Printed ${rep_sub} vs Calculated ${sum_lines}"
                        else:
                            audit_field = "Document Arithmetic"
                            audit_val = "Math validation failed on document"

                    val_evidence.append(
                        Evidence(
                            evidence_id=ev_id,
                            source_type=stype,
                            source_id=doc_id,
                            field=audit_field,
                            value=audit_val,
                            description=clean_reason,
                        )
                    )
                    val_findings.append(
                        Finding(
                            finding_id=f_id,
                            discrepancy_type="CALCULATION_ERROR",
                            explanation=(
                                f"Document validation failed: {clean_reason} "
                                f"Payment cannot be approved until a corrected document is provided by the vendor."
                            ),
                            supporting_evidence_ids=[ev_id],
                            confidence="HIGH",
                        )
                    )

            rejection_summary = (
                f"Invoice rejected: Internal arithmetic validation failed. "
                f"{'; '.join(val_errors)}. "
                f"Action: Request a corrected document from the vendor."
            )

            inv_res = InvestigationResult(
                case_id=active_case_id,
                findings=val_findings,
                evidence=val_evidence,
                recommendation="REJECT_INVOICE",
                confidence="HIGH",
                requires_human_review=True,
                final_summary=rejection_summary,
            )

            recommendation = inv_res.recommendation
            confidence = inv_res.confidence
            requires_human_review = inv_res.requires_human_review
            inv_result_dict = inv_res.model_dump()

            if self.db:
                clean_state = {
                    "case_id": active_case_id,
                    "reconciliation_result": recon_res.model_dump(),
                    "discrepancies": discrepancies_list,
                    "findings": [f.model_dump() for f in val_findings],
                    "evidence": [e.model_dump() for e in val_evidence],
                    "final_summary": rejection_summary,
                    "recommendation": "REJECT_INVOICE",
                    "confidence": "HIGH",
                    "requires_human_review": True,
                    "status": "REJECTED",
                    "po_file": po_file,
                    "invoice_file": inv_file,
                    "receipt_files": rcpt_files,
                    "source_files": all_files,
                    "vendor_name": vendor_name,
                    "po_number": po_num,
                    "invoice_number": inv_num,
                    "receipt_numbers": rcpt_nums,
                }
                self.db.save_investigation(
                    state=clean_state,
                    result=inv_res,
                    po_file=po_file,
                    invoice_file=inv_file,
                    receipt_files=rcpt_files,
                    source_files=all_files,
                    vendor_name=vendor_name,
                    po_number=po_num,
                    invoice_number=inv_num,
                    receipt_numbers=rcpt_nums,
                    reconciliation_result=recon_res.model_dump(),
                )

            if self.review_queue:
                self.review_queue.enqueue(
                    case_id=active_case_id,
                    discrepancy_count=discrepancy_count,
                    recommendation="REJECT_INVOICE",
                    confidence="HIGH",
                    requires_human_review=True,
                    metadata=clean_state if self.db else {},
                    discrepancies=discrepancies_list,
                    findings=val_findings,
                    evidence=val_evidence,
                )

        else:
            # PROBLEMS DETECTED -> AGENT INVESTIGATION
            logger.info(
                f"[Orchestrator] Case {active_case_id}: {discrepancy_count} discrepancies flagged. "
                f"Dispatching to LangGraph AI Investigation Agent..."
            )

            # Populate sandboxed agent datastore for this case
            agent_store = AgentDataStore()
            if po_data:
                p_id = po_data.get("purchase_order_number") or po_data.get("po_number") or active_case_id
                agent_store.add_purchase_order(p_id, po_data)

            if invoice_data:
                i_id = invoice_data.get("invoice_number") or active_case_id
                agent_store.add_invoice(i_id, invoice_data)

            for rcpt in receipts:
                r_id = rcpt.get("receipt_number") or rcpt.get("delivery_receipt_number")
                if r_id:
                    agent_store.add_receipt(r_id, rcpt)

            # Execute LangGraph autonomous reasoning loop
            inv_res: InvestigationResult = run_investigation(
                reconciliation_result=recon_res,
                datastore=agent_store,
                max_tool_calls=self.max_tool_calls,
                client=self.client,
                db=self.db,
                review_queue=self.review_queue,
                agent_logger=self.agent_logger,
                po_file=po_file,
                invoice_file=inv_file,
                receipt_files=rcpt_files,
                source_files=all_files,
                vendor_name=vendor_name,
                po_number=po_num,
                invoice_number=inv_num,
                receipt_numbers=rcpt_nums,
            )

            recommendation = inv_res.recommendation
            confidence = inv_res.confidence
            requires_human_review = inv_res.requires_human_review
            inv_result_dict = inv_res.model_dump()

        duration_ms = (time.perf_counter() - t_start) * 1000.0

        return TransactionResult(
            case_id=active_case_id,
            po_number=po_num,
            invoice_number=inv_num,
            receipt_numbers=rcpt_nums,
            po_file=po_file,
            invoice_file=inv_file,
            receipt_files=rcpt_files,
            source_files=all_files,
            status=recon_res.status.value,
            recommendation=recommendation,
            confidence=confidence,
            requires_human_review=requires_human_review,
            discrepancy_count=discrepancy_count,
            discrepancies=discrepancies_list,
            reconciliation_result=recon_res.model_dump(),
            investigation_result=inv_result_dict,
            duration_ms=duration_ms,
        )

    # =========================================================================
    # FILE INGESTION & DOCUMENT ASSEMBLY LINE
    # =========================================================================
    def process_files(
        self,
        file_paths: List[Union[str, Path]],
        case_id_override: Optional[str] = None,
    ) -> OrchestrationReport:
        """
        Coordinates the entire assembly line on a set of incoming files:
          1. Ingestion: Reads files
          2. Classifier: Classifies into PO, Invoice, Receipt
          3. Extractor: Extracts structured data
          4. Validator: Checks math arithmetic
          5. Grouping: Groups documents into transaction sets
          6. Reconciliation & Agent Investigation
          7. Persistence & Review Queue
        """
        t_batch_start = time.perf_counter()
        doc_items: List[DocumentItem] = []

        logger.info(f"[Orchestrator] Ingesting & classifying {len(file_paths)} incoming files...")

        # ---------------------------------------------------------------------
        # STEPS 1 & 2: INGESTION & CLASSIFICATION
        # ---------------------------------------------------------------------
        for p_raw in file_paths:
            p = Path(p_raw)
            if not p.is_file():
                logger.warning(f"[Orchestrator] Skipping non-file path: {p}")
                continue

            # Step 1: Ingest document (handles TXT, PDF, images, scanned files)
            try:
                raw_document = ingest_document(p)
            except Exception as exc:
                logger.error(f"[Orchestrator] Ingestion failed on {p}: {exc}")
                continue

            # Step 2: Classify document
            try:
                class_res = classify_document(raw_document)
                doc_type = class_res.document_type.value
            except Exception as exc:
                logger.error(f"[Orchestrator] Classification failed on {p}: {exc}")
                doc_type = DocumentType.UNKNOWN.value

            # Step 3: Unified Structured Extraction
            extracted: Dict[str, Any] = {}
            try:
                extracted = extract_document(raw_document, doc_type, client=self.client)
            except Exception as exc:
                logger.error(f"[Orchestrator] Extraction failed on {p}: {exc}")

            # -----------------------------------------------------------------
            # STEP 4: ARITHMETIC VALIDATION
            # -----------------------------------------------------------------
            val_errors: List[str] = []
            val_status = "VALID"
            try:
                if doc_type == DocumentType.INVOICE.value and extracted:
                    val_res = verify_invoice_math(extracted)
                    if not val_res.get("is_valid", True):
                        val_status = "INVALID_MATH"
                        val_errors = [d.get("message", str(d)) if isinstance(d, dict) else str(d) for d in val_res.get("discrepancies", [])]
                elif doc_type == DocumentType.PURCHASE_ORDER.value and extracted:
                    val_res = verify_purchase_order_math(extracted)
                    if not val_res.get("is_valid", True):
                        val_status = "INVALID_MATH"
                        val_errors = [d.get("message", str(d)) if isinstance(d, dict) else str(d) for d in val_res.get("discrepancies", [])]
                elif doc_type == DocumentType.RECEIPT.value and extracted:
                    val_res = verify_receipt_math(extracted)
                    if not val_res.get("is_valid", True):
                        val_status = "INVALID_MATH"
                        val_errors = [d.get("message", str(d)) if isinstance(d, dict) else str(d) for d in val_res.get("discrepancies", [])]
            except Exception as exc:
                logger.warning(f"[Orchestrator] Math validation error on {p}: {exc}")

            doc_items.append(DocumentItem(
                file_path=str(p),
                document_type=doc_type,
                extracted_data=extracted,
                validation_status=val_status,
                validation_errors=val_errors,
            ))

        # ---------------------------------------------------------------------
        # STEP 5: TRANSACTION GROUPING
        # ---------------------------------------------------------------------
        grouped = self._group_documents_into_transactions(doc_items, case_id_override)
        logger.info(f"[Orchestrator] Grouped {len(doc_items)} documents into {len(grouped)} transactions.")

        # ---------------------------------------------------------------------
        # STEPS 6 & 7: RECONCILIATION & AGENT EXECUTION
        # ---------------------------------------------------------------------
        tx_results: List[TransactionResult] = []
        matched_clean = 0
        flagged = 0
        investigated = 0
        sent_to_queue = 0

        for trx_key, group in grouped.items():
            po = group.get("po")
            inv = group.get("invoice")
            rcpts = group.get("receipts", [])

            res = self.process_transaction(
                po_data=po,
                invoice_data=inv,
                receipt_data_list=rcpts,
                case_id=trx_key,
            )
            tx_results.append(res)

            if res.discrepancy_count == 0:
                matched_clean += 1
            else:
                flagged += 1
                investigated += 1

            if res.requires_human_review:
                sent_to_queue += 1

        overall_ms = (time.perf_counter() - t_batch_start) * 1000.0

        return OrchestrationReport(
            total_documents=len(doc_items),
            total_transactions=len(grouped),
            matched_clean=matched_clean,
            discrepancies_flagged=flagged,
            investigated_by_agent=investigated,
            sent_to_review_queue=sent_to_queue,
            transactions=tx_results,
            overall_duration_ms=overall_ms,
        )

    def process_directory(
        self,
        directory_path: Union[str, Path],
        file_pattern: str = "*.txt",
    ) -> OrchestrationReport:
        """
        Coordinates document processing for all matching files in an input directory.
        """
        dir_p = Path(directory_path)
        if not dir_p.is_dir():
            raise ValueError(f"Target path '{directory_path}' is not a valid directory.")

        files = sorted(dir_p.glob(file_pattern))
        return self.process_files(files)

    # =========================================================================
    # CONTENT-DRIVEN DOCUMENT LINKER & GROUPING
    # =========================================================================
    def _group_documents_into_transactions(
        self,
        doc_items: List[DocumentItem],
        case_id_override: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Groups extracted documents into transaction triplets (PO, Invoice, Receipts)
        based on transaction ID prefix, PO reference, or case ID.
        Content-driven document grouping powered by DocumentLinker.
        Discovers commercial relationships between POs, Invoices, and Receipts
        from extracted document content (PO numbers, references, vendor/amount proximity)
        rather than relying on filenames.
        """
        groups: Dict[str, Dict[str, Any]] = {}
        # If explicit caller override is supplied, bind all to one case
        if case_id_override:
            po = None
            inv = None
            rcpts = []
            for item in doc_items:
                data = item.extracted_data
                data["_source_file"] = item.file_path
                if item.document_type == DocumentType.PURCHASE_ORDER.value:
                    po = data
                elif item.document_type == DocumentType.INVOICE.value:
                    inv = data
                elif item.document_type == DocumentType.RECEIPT.value:
                    rcpts.append(data)
            return {case_id_override: {"po": po, "invoice": inv, "receipts": rcpts}}

        # 1. Bucket documents by extracted type
        pos: List[Dict[str, Any]] = []
        invoices: List[Dict[str, Any]] = []
        receipts: List[Dict[str, Any]] = []

        for item in doc_items:
            data = item.extracted_data
            data["_source_file"] = item.file_path

            if item.document_type == DocumentType.PURCHASE_ORDER.value:
                pos.append(data)
            elif item.document_type == DocumentType.INVOICE.value:
                invoices.append(data)
            elif item.document_type == DocumentType.RECEIPT.value:
                receipts.append(data)

        # 2. Index Primary Commercial Anchors (Purchase Orders)
        cases: Dict[str, Dict[str, Any]] = {}
        po_number_to_case_id: Dict[str, str] = {}

        for idx, po in enumerate(pos):
            po_num = po.get("purchase_order_number") or po.get("po_number")
            trx_id = po.get("transaction_id")

            # Case Key: transaction_id if present in content, else po_num, else unique ID
            case_id = trx_id or po_num or f"PO_CASE_{idx+1:04d}"
            cases[case_id] = {
                "po": po,
                "invoice": None,
                "receipts": [],
                "linking_evidence": None,
            }
            if po_num:
                po_number_to_case_id[po_num] = case_id
                norm_key = normalize_po_number(po_num)
                if norm_key:
                    po_number_to_case_id[norm_key] = case_id

        # 3. Content-Based Invoice Linking (via DocumentLinker relationships)
        unlinked_invoices: List[Dict[str, Any]] = []

        for inv in invoices:
            inv_po_ref = inv.get("purchase_order_number") or inv.get("po_number")
            inv_trx_id = inv.get("transaction_id")

            matched_case_id = None

            # 3a. Direct PO Number Content Match (with normalization)
            norm_inv_po = normalize_po_number(inv_po_ref) if inv_po_ref else ""
            if inv_po_ref and inv_po_ref in po_number_to_case_id:
                matched_case_id = po_number_to_case_id[inv_po_ref]
            elif norm_inv_po and norm_inv_po in po_number_to_case_id:
                matched_case_id = po_number_to_case_id[norm_inv_po]

            # 3b. Content Transaction ID Match (e.g. ERP metadata)
            elif inv_trx_id and inv_trx_id in cases:
                matched_case_id = inv_trx_id

            # 3c. DocumentLinker Fuzzy Match (for invoices without explicit PO reference)
            if not matched_case_id:
                best_score = 0.0
                best_candidate_id = None
                best_evidence = None

                for c_id, c_data in cases.items():
                    if c_data["invoice"] is None and c_data["po"] is not None:
                        link_evidence = evaluate_link(po_data=c_data["po"], invoice_data=inv)
                        if link_evidence.score > best_score:
                            best_score = link_evidence.score
                            best_candidate_id = c_id
                            best_evidence = link_evidence

                # Link if DocumentLinker achieves high confidence (>= 0.70)
                if best_score >= 0.70 and best_candidate_id:
                    matched_case_id = best_candidate_id
                    cases[best_candidate_id]["linking_evidence"] = best_evidence

            # Assign to matched case, or mark unlinked
            if matched_case_id and cases[matched_case_id]["invoice"] is None:
                cases[matched_case_id]["invoice"] = inv
            else:
                unlinked_invoices.append(inv)

        # 4. Content-Based Receipt Linking (via DocumentLinker relationships)
        unlinked_receipts: List[Dict[str, Any]] = []

        for rcpt in receipts:
            rcpt_po_ref = rcpt.get("purchase_order_number") or rcpt.get("po_number")
            rcpt_trx_id = rcpt.get("transaction_id")

            matched_case_id = None

            # 4a. Direct PO Number Content Match (with normalization)
            norm_rcpt_po = normalize_po_number(rcpt_po_ref) if rcpt_po_ref else ""
            if rcpt_po_ref and rcpt_po_ref in po_number_to_case_id:
                matched_case_id = po_number_to_case_id[rcpt_po_ref]
            elif norm_rcpt_po and norm_rcpt_po in po_number_to_case_id:
                matched_case_id = po_number_to_case_id[norm_rcpt_po]

            # 4b. Content Transaction ID Match
            elif rcpt_trx_id and rcpt_trx_id in cases:
                matched_case_id = rcpt_trx_id

            # 4c. Receipt referencing an Invoice Number
            elif rcpt.get("invoice_number"):
                inv_target = rcpt.get("invoice_number")
                for c_id, c_data in cases.items():
                    if c_data.get("invoice") and c_data["invoice"].get("invoice_number") == inv_target:
                        matched_case_id = c_id
                        break

            # 4d. DocumentLinker Evaluation against POs
            if not matched_case_id:
                best_score = 0.0
                best_candidate_id = None
                for c_id, c_data in cases.items():
                    if c_data["po"] is not None:
                        link_evidence = evaluate_link(po_data=c_data["po"], receipt_data_list=[rcpt])
                        if link_evidence.score > best_score:
                            best_score = link_evidence.score
                            best_candidate_id = c_id
                if best_score >= 0.70 and best_candidate_id:
                    matched_case_id = best_candidate_id

            if matched_case_id:
                cases[matched_case_id]["receipts"].append(rcpt)
            else:
                unlinked_receipts.append(rcpt)

        # 5. Handle Unlinked / Standalone Invoices (Missing PO reference cases)
        for idx, inv in enumerate(unlinked_invoices):
            inv_num = inv.get("invoice_number") or f"INV_{idx+1:04d}"
            case_id = inv.get("transaction_id") or f"CASE_{inv_num}"
            cases[case_id] = {
                "po": None,
                "invoice": inv,
                "receipts": [],
                "linking_evidence": None,
            }

        # 6. Handle Unlinked Receipts
        for idx, rcpt in enumerate(unlinked_receipts):
            rcpt_num = rcpt.get("receipt_number") or f"RCPT_{idx+1:04d}"
            case_id = rcpt.get("transaction_id") or f"CASE_{rcpt_num}"
            cases[case_id] = {
                "po": None,
                "invoice": None,
                "receipts": [rcpt],
                "linking_evidence": None,
            }

        return cases


# =============================================================================
# CLI TERMINAL ENTRYPOINT
# =============================================================================
def main():
    """
    Command-line runner for the Master Pipeline Orchestrator.
    Processes documents, runs 3-way reconciliation, triggers autonomous AI agent
    investigations for discrepancies, and outputs a formatted dashboard on screen.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="ReconAgent Master Pipeline Orchestrator: End-to-End Ingestion, Reconciliation & Investigation"
    )

    # -------------------------------------------------------------------------
    # DATASET DIRECTORY CONFIGURATION (CHANGE DEFAULT PATH HERE IF DESIRED)
    # -------------------------------------------------------------------------
    # default_dataset_dir = PROJECT_ROOT / "dataset" / "mock_reconciliation"
    default_dataset_dir = PROJECT_ROOT / "dataset" / "mock_reconciliati"
    
    if not default_dataset_dir.exists():
        default_dataset_dir = PROJECT_ROOT / "dataset" / "mock_reconciliation_100" / "mixed_documents"

    parser.add_argument(
        "--dir", "-d",
        type=str,
        default=str(default_dataset_dir),
        help=f"Path to folder containing documents to process (default: {default_dataset_dir})",
    )
    parser.add_argument(
        "--pattern", "-p",
        type=str,
        default="*.txt",
        help="Glob pattern for document files (default: *.txt)",
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=0,
        help="Max files to process (default: 15; use 0 for all)",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(PROJECT_ROOT / "data" / "investigations.db"),
        help="Path to SQLite audit database (default: data/investigations.db)",
    )

    args = parser.parse_args()
    target_dir = Path(args.dir)

    if not target_dir.exists() or not target_dir.is_dir():
        print(f"[Error] Directory not found: {target_dir}")
        sys.exit(1)

    # Discover target files recursively, filtering out non-document files (e.g. metadata json)
    all_files = sorted([
        f for f in target_dir.rglob(args.pattern)
        if f.is_file() and not f.name.endswith(".json")
    ])
    if not all_files:
        all_files = sorted([
            f for f in target_dir.rglob("*")
            if f.is_file() and not f.name.endswith(".json") and f.suffix.lower() in {".txt", ".pdf", ".png", ".jpg", ".jpeg"}
        ])

    if not all_files:
        print(f"[Warning] No matching document files found in {target_dir}")
        sys.exit(0)

    # Group files by transaction prefix so every transaction has its complete PO + Invoice + Receipt
    trx_map = {}
    for f in all_files:
        parts = f.stem.split("_")
        if len(parts) >= 3 and parts[0] == "TRX":
            prefix = "_".join(parts[:3])
        else:
            prefix = f.stem
        trx_map.setdefault(prefix, []).append(f)

    sorted_pfx = sorted(trx_map.keys())
    if args.limit > 0:
        # Calculate how many cases fit into the limit (assuming ~3 docs per case)
        target_cases_count = max(1, args.limit // 3)
        selected_pfx = sorted_pfx[:target_cases_count]
        selected_files = []
        for pfx in selected_pfx:
            selected_files.extend(trx_map[pfx])
    else:
        selected_files = all_files

    print("\n" + "=" * 80)
    print("   RECONAGENT: MASTER PIPELINE ORCHESTRATOR")
    print("   Autonomous 3-Way Reconciliation & Forensic Investigation System")
    print("=" * 80)
    print(f"Target Directory : {target_dir}")
    print(f"Documents Loaded : {len(selected_files)} files ({len(selected_pfx) if args.limit > 0 else len(sorted_pfx)} transaction sets)")
    print(f"Audit Database   : {args.db}")
    print("=" * 80 + "\n")

    orchestrator = MasterOrchestrator(db_path=args.db)

    try:
        report: OrchestrationReport = orchestrator.process_files(selected_files)

        # Print Summary Dashboard
        print("\n" + "=" * 80)
        print("                     ORCHESTRATION PIPELINE SUMMARY")
        print("=" * 80)
        print(f"Total Documents Ingested     : {report.total_documents}")
        print(f"Total Transactions Formed    : {report.total_transactions}")
        print(f"Clean Matches (Auto-Approved): {report.matched_clean}")
        print(f"Discrepancies Flagged        : {report.discrepancies_flagged}")
        print(f"Investigated by AI Agent     : {report.investigated_by_agent}")
        print(f"Sent to Human Review Queue   : {report.sent_to_review_queue}")
        print(f"Total Duration               : {report.overall_duration_ms:.1f} ms")
        print("=" * 80)

        # Detailed Transaction Breakdown Table
        print("\n" + "-" * 140)
        print(f"{'CASE ID':<18} | {'PO NUMBER':<15} | {'INVOICE NO':<14} | {'STATUS':<15} | {'RECOMMENDATION':<20} | {'DISC':<4} | {'FILES'}")
        print("-" * 140)
        for tx in report.transactions:
            po_str = tx.po_number or "N/A"
            inv_str = tx.invoice_number or "N/A"
            files_str = ", ".join(tx.source_files) if tx.source_files else "N/A"
            print(
                f"{tx.case_id:<18} | "
                f"{po_str:<15} | "
                f"{inv_str:<14} | "
                f"{tx.status:<15} | "
                f"{tx.recommendation:<20} | "
                f"{tx.discrepancy_count:<4} | "
                f"{files_str}"
            )
        print("-" * 140)

        # Print Complete Forensic Reports for ALL Flagged / Investigated Transactions
        investigated_txs = [t for t in report.transactions if t.discrepancy_count > 0]
        if investigated_txs:
            print("\n" + "#" * 80)
            print("         AUTONOMOUS AI INVESTIGATION AGENT: COMPLETE FORENSIC REPORTS")
            print("#" * 80)

            for idx, tx in enumerate(investigated_txs, start=1):
                inv = tx.investigation_result or {}
                findings = inv.get("findings", [])
                evidence = inv.get("evidence", [])

                po_display = tx.po_number or "N/A (Missing from document)"
                inv_display = tx.invoice_number or "N/A (Missing from document)"
                rcpt_display = ", ".join(tx.receipt_numbers) if tx.receipt_numbers else "N/A"

                po_file_disp = f" (File: {tx.po_file})" if tx.po_file else ""
                inv_file_disp = f" (File: {tx.invoice_file})" if tx.invoice_file else ""
                rcpt_files_disp = f" (Files: {', '.join(tx.receipt_files)})" if tx.receipt_files else ""

                print("\n" + "=" * 80)
                print(f"CASE [{idx}/{len(investigated_txs)}]: {tx.case_id}")
                print(f"PO NUMBER              : {po_display}{po_file_disp}")
                print(f"INVOICE NUMBER         : {inv_display}{inv_file_disp}")
                print(f"RECEIPT NUMBER(S)      : {rcpt_display}{rcpt_files_disp}")
                if tx.source_files:
                    print(f"MATCHED SOURCE FILES   : {', '.join(tx.source_files)}")
                print("=" * 80)
                print(f"Reconciliation Status  : {tx.status}")
                print(f"Final Recommendation   : {tx.recommendation}")
                print(f"Confidence Level       : {tx.confidence}")
                print(f"Human Specialist Review: {'REQUIRED (Routed to Review Queue)' if tx.requires_human_review else 'NOT REQUIRED'}")

                # 1. 3-Way Reconciliation Discrepancies
                print(f"\n[1] Discrepancies Detected by 3-Way Reconciliation ({len(tx.discrepancies)}):")
                for d_idx, d in enumerate(tx.discrepancies, start=1):
                    dtype = d.get('type', 'DISCREPANCY')
                    sev = d.get('severity', 'HIGH')
                    expl = d.get('explanation') or d.get('details') or ''
                    print(f"    {d_idx}. [{sev}] {dtype}: {expl}")

                # 2. Agent Findings
                print(f"\n[2] Agent Verified Forensic Findings ({len(findings)}):")
                if findings:
                    for f in findings:
                        fid = f.get('finding_id', 'FINDING')
                        ftype = f.get('discrepancy_type', '')
                        fconf = f.get('confidence', 'HIGH')
                        fexpl = f.get('explanation', '')
                        fevid = ", ".join(f.get('supporting_evidence_ids', [])) or 'None'
                        print(f"    - [{fid}] {ftype} ({fconf} Confidence):")
                        print(f"        Explanation        : {fexpl}")
                        print(f"        Supporting Evidence: {fevid}")
                else:
                    print("    - No findings emitted.")

                # 3. Agent Grounded Evidence
                print(f"\n[3] Grounded Evidence Gathered by Agent ({len(evidence)}):")
                if evidence:
                    for e in evidence:
                        eid = e.get('evidence_id', 'EVID')
                        esrc = e.get('source_type', 'doc')
                        esrc_id = e.get('source_id', '')
                        efield = e.get('field') or 'general'
                        eval_ = e.get('value')
                        edesc = e.get('description', '')
                        val_display = f" = {eval_}" if eval_ is not None else ""
                        print(f"    - [{eid}] Source: {esrc.upper()} ({esrc_id}) | Field: {efield}{val_display}")
                        print(f"        Observation: {edesc}")
                else:
                    print("    - No evidence records gathered.")

                # 4. Actionable Next Step
                print(f"\n[4] Prescribed Settlement Action:")
                print(f"    >>> Action Code: {tx.recommendation}")
                if tx.recommendation == "REQUEST_CREDIT_MEMO":
                    print("    >>> Reason     : Vendor invoiced for unreceived items or unapproved price variance.")
                    print("    >>> Next Step  : Issue formal credit memo request to vendor before payment.")
                elif tx.recommendation == "REJECT_INVOICE":
                    print("    >>> Reason     : Severe non-compliance or duplicate billing detected.")
                    print("    >>> Next Step  : Reject invoice in ERP and notify vendor.")
                elif tx.recommendation == "ESCALATE_TO_BUYER":
                    print("    >>> Reason     : Insufficient documentary evidence on file.")
                    print("    >>> Next Step  : Escalate case to procurement buyer for confirmation.")
                elif tx.recommendation == "APPROVE_PAYMENT":
                    print("    >>> Reason     : Price change or variance confirmed authorized on file.")
                    print("    >>> Next Step  : Release payment in full.")
                print("=" * 80)

            print("\n" + "#" * 80 + "\n")

    finally:
        orchestrator.close()


if __name__ == "__main__":
    main()


