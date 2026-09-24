"""
Enterprise-Grade Document Classifier for Ingestion & Routing.

Classifies incoming mixed documents into:
- INVOICE (commercial vendor bills, payment requests)
- PURCHASE_ORDER (procurement orders, buyer agreements)
- RECEIPT (point-of-sale slips, retail tapes, delivery confirmation receipts)
- UNKNOWN (unrecognized or non-business documents)

Architecture:
- Tier 1: Instant Local Text Extraction & Semantic Heuristics (<5ms per doc, 100% local, zero cost).
- Tier 2: Multimodal Vision Analysis with Gemini 3.5 Flash Lite for scanned PDFs & images.
- Dispatcher: Directory-level sorting (copy/move) and downstream pipeline routing.
"""
import os
import re
import sys
import time
import json
import shutil
import logging
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = SRC_ROOT.parent
DEFAULT_INBOX_DIR = PROJECT_ROOT / "dataset" / "inbox"
DEFAULT_ORGANIZED_DIR = PROJECT_ROOT / "dataset" / "organized"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from typing import Optional, Union, List, Dict, Any, Tuple

from dotenv import load_dotenv
load_dotenv()

from pydantic import BaseModel, Field
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from google import genai
from google.genai import types

from schemas.document_classification import (
    DocumentType,
    PipelineTarget,
    ClassificationResult,
    BatchClassificationReport,
)

try:
    from .document_ingestion import IngestedDocument, ingest_document
except (ImportError, ValueError):
    from ingestion.document_ingestion import IngestedDocument, ingest_document


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("DocumentClassifier")

# Model configuration
VISION_MODEL_NAME = "gemini-3.5-flash-lite"
SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".txt"}
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB


class _VisionClassificationOutput(BaseModel):
    """Pydantic schema for structured Gemini Vision classification."""
    document_type: str = Field(description="Must be exactly 'invoice', 'purchase_order', 'receipt', or 'unknown'")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")
    reasoning: str = Field(description="Clear explanation of the visual and structural features leading to this classification")
    key_indicators: List[str] = Field(default_factory=list, description="Specific header, logo, or field cues identified")


VISION_CLASSIFICATION_PROMPT = """
You are an expert document classification system for an enterprise Accounts Payable and Reconciliation engine.
Analyze the provided document image or PDF and classify it into EXACTLY one category:

1. "receipt":
   - Proof of physical retail transaction, completed customer payment, or merchandise delivery handover.
   - Includes:
     a) Point-of-Sale (POS) slips, thermal paper register tapes, retail store slips (e.g. supermarket, pharmacy, hardware, convenience store).
     b) Dining bills / restaurant checks showing cash/card tender, subtotal, and tip/service charge.
     c) Delivery receipts / packing slips showing delivered goods, carrier tracking number, and recipient signature/acknowledgement.
   - Distinctive features: narrow receipt roll or POS layout, 'Cash Bill', 'Official Receipt', 'Delivery Receipt', 'Cashier', 'Tendered', 'Change Due', 'Payment Mode', 'Delivered To', 'Carrier', 'Received By'.
   - CRITICAL RULE FOR RETAIL "TAX INVOICES": In many jurisdictions (Malaysia, Singapore, Australia, UK), retail store receipts are titled "TAX INVOICE" or "SIMPLIFIED TAX INVOICE" for GST/VAT reporting. If the document is a retail store slip, supermarket receipt, or dining check showing instant payment (Cash, Card, Cashier, Change Due, Tendered), it MUST be classified as a "receipt", NOT an invoice!

2. "invoice":
   - Formal commercial Accounts Payable (AP) billing documents issued by a vendor/seller requesting payment from a corporate or business buyer.
   - Distinctive features: 'Invoice', 'Bill To' corporate address, 'Invoice Number', 'Invoice Date', payment terms (e.g. 'Net 30', 'Net 60'), payment due date, bank remittance / wire transfer details, accounts payable department address.
   - Distinct from receipts: Invoices request future payment (they do not show a cashier handing back change).

3. "purchase_order":
   - Formal procurement or purchase order issued by a buyer/purchasing department authorizing the purchase of goods or services from a vendor.
   - Distinctive features: 'Purchase Order', 'Purchase Orders', 'PO Number', 'Order ID', 'Order Date', 'Purchasing Dept', 'Authorized Signature', 'FOB Point', 'Ship To' warehouse address, buyer requisition details.

4. "unknown":
   - Any document that is clearly NOT a business invoice, purchase order, or receipt (e.g. personal letters, random photos, promotional flyers, generic articles).

Respond strictly according to the requested JSON schema.
"""


def get_gemini_client() -> Optional[genai.Client]:
    """Initializes and returns the Gemini API client if API key is present."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY environment variable is not set. Multimodal vision fallback will be unavailable.")
        return None
    return genai.Client(api_key=api_key)


def extract_text_if_available(file_path: Path) -> Optional[str]:
    """
    Attempts to extract raw text from digital files (.txt or text-based .pdf).
    Returns None if the file is an image, a scanned PDF with no text layer, or unreadable.
    """
    try:
        doc = ingest_document(file_path, extract_text=True)
        return doc.text_content if doc.has_text else None
    except Exception as exc:
        logger.debug(f"Extraction skipped or failed for '{file_path.name}': {exc}")
        return None



def classify_text_heuristics(text: str, file_path: Path) -> Optional[ClassificationResult]:
    """
    Tier 1 Engine: Fast structural and semantic keyword scoring for text content.
    Returns a ClassificationResult if confident (>= 0.85), or None if ambiguous.
    """
    if not text or len(text.strip()) < 15:
        return None

    lower = text.lower()
    first_lines = "\n".join(lower.splitlines()[:12])

    po_score = 0
    inv_score = 0
    rcpt_score = 0
    indicators: List[str] = []

    # ------------------------------------------------------------
    # 1. Prominent Title & Document Header Matching
    # ------------------------------------------------------------
    if re.search(r"\bpurchase\s+orders?\b", first_lines):
        po_score += 15
        indicators.append("Title: Purchase Order")
    elif re.search(r"\bp\.o\.(\s+number)?\b", first_lines):
        po_score += 10
        indicators.append("Title: P.O.")

    if re.search(r"\bdelivery\s+receipt\b", first_lines):
        rcpt_score += 15
        indicators.append("Title: Delivery Receipt")
    elif re.search(r"\b(sales\s+receipt|cash\s+receipt|official\s+receipt)\b", first_lines):
        rcpt_score += 15
        indicators.append("Title: Official/Sales Receipt")
    elif re.search(r"\breceipt\b", first_lines) and not re.search(r"\binvoice\b", first_lines):
        rcpt_score += 10
        indicators.append("Title: Receipt")

    if re.search(r"\b(tax\s+invoice|commercial\s+invoice|invoice)\b", first_lines) and "delivery receipt" not in first_lines:
        inv_score += 15
        indicators.append("Title: Invoice")

    # ------------------------------------------------------------
    # 2. Purchase Order Specific Fields & Terms
    # ------------------------------------------------------------
    if re.search(r"\bpo\s+number:\s*[A-Za-z0-9\-]+", lower):
        po_score += 7
        indicators.append("Explicit PO Number field")
    if "order id" in lower and "order date" in lower:
        po_score += 8
        indicators.append("Order ID and Order Date")
    if "purchasing dept" in lower or "authorized signature:" in lower:
        po_score += 6
        indicators.append("Purchasing Dept / Authorized Signature")
    if "fob point:" in lower or "vendor:" in lower and "ship to:" in lower:
        po_score += 5
        indicators.append("FOB / Shipping Terms")

    # ------------------------------------------------------------
    # 3. Invoice Specific Fields & Terms
    # ------------------------------------------------------------
    if re.search(r"\binvoice\s+number:\s*[A-Za-z0-9\-]+", lower):
        inv_score += 7
        indicators.append("Explicit Invoice Number field")
    if "payment due date:" in lower or "due date:" in lower:
        inv_score += 6
        indicators.append("Payment Due Date")
    if "remit to:" in lower or "remittance" in lower:
        inv_score += 6
        indicators.append("Remit To payment instructions")
    if re.search(r"payment terms:\s*net\s*\d+", lower):
        inv_score += 5
        indicators.append("Payment Terms (Net terms)")
    if "bill to:" in lower and ("po reference:" in lower or "remit to:" in lower):
        inv_score += 5
        indicators.append("Commercial Bill To / Remit To / PO Reference")

    # ------------------------------------------------------------
    # 4. Receipt Specific Fields & Terms
    # ------------------------------------------------------------
    if re.search(r"\breceipt\s+number:\s*[A-Za-z0-9\-]+", lower):
        rcpt_score += 7
        indicators.append("Explicit Receipt Number field")
    if "delivery date:" in lower or "delivered to:" in lower or "carrier:" in lower:
        rcpt_score += 7
        indicators.append("Carrier / Delivery tracking details")
    if "qty delivered" in lower or "received by:" in lower or "time of delivery:" in lower:
        rcpt_score += 7
        indicators.append("Proof of delivery / Received by signature")
    if "cashier:" in lower or "change due:" in lower or "gst summary" in lower or "rounding adj" in lower:
        rcpt_score += 6
        indicators.append("POS / retail cash register breakdown")

    # ------------------------------------------------------------
    # 5. Score Resolution & Confidence
    # ------------------------------------------------------------
    scores = {
        DocumentType.PURCHASE_ORDER: po_score,
        DocumentType.INVOICE: inv_score,
        DocumentType.RECEIPT: rcpt_score,
    }

    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]

    # Check margin of victory over runner-up
    sorted_scores = sorted(scores.values(), reverse=True)
    lead_margin = sorted_scores[0] - sorted_scores[1]

    if best_score >= 10 and lead_margin >= 5:
        # High confidence match
        confidence = min(0.99, 0.90 + (best_score / 100.0))
        pipeline_map = {
            DocumentType.INVOICE: PipelineTarget.INVOICE_PIPELINE,
            DocumentType.PURCHASE_ORDER: PipelineTarget.PO_PIPELINE,
            DocumentType.RECEIPT: PipelineTarget.RECEIPT_PIPELINE,
        }
        return ClassificationResult(
            file_name=file_path.name,
            file_path=str(file_path.resolve()),
            document_type=best_type,
            confidence=round(confidence, 2),
            tier_used="local_text",
            reasoning=f"High-confidence semantic text match for {best_type.value} based on structural markers.",
            key_indicators=indicators,
            suggested_pipeline=pipeline_map[best_type],
        )

    return None


def classify_multimodal_vision(client: genai.Client, file_path: Path) -> ClassificationResult:
    """
    Tier 2 Engine: Multimodal vision analysis using Gemini 3.5 Flash Lite
    for scanned PDFs and retail image formats (.jpg, .png, etc.).
    Includes exponential backoff and quota recovery.
    """
    file_ext = file_path.suffix.lower()
    contents: List[Any] = [VISION_CLASSIFICATION_PROMPT]
    uploaded_file = None

    max_retries = 5
    base_delay = 2.0
    backoff_factor = 2.0

    try:
        if file_ext == ".pdf":
            logger.info(f"[Tier 2] Uploading PDF to Gemini File API for vision classification: {file_path.name}")
            uploaded_file = client.files.upload(file=str(file_path))
            contents.append(uploaded_file)
        elif file_ext in (".txt", ".csv", ".tsv", ".json", ".log"):
            txt_content = file_path.read_text(encoding="utf-8", errors="replace")[:4000]
            contents.append(f"Document Text Content:\n{txt_content}")
        elif file_ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"):
            image = Image.open(file_path)
            contents.append(image)
        else:
            return ClassificationResult(
                file_name=file_path.name,
                file_path=str(file_path.resolve()),
                document_type=DocumentType.UNKNOWN,
                confidence=0.0,
                tier_used="unsupported_format",
                reasoning=f"Unsupported file format '{file_ext}'.",
                key_indicators=[],
                suggested_pipeline=PipelineTarget.MANUAL_REVIEW,
            )

        for attempt in range(1, max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=VISION_MODEL_NAME,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=_VisionClassificationOutput,
                        temperature=0.0,
                    )
                )

                output: Optional[_VisionClassificationOutput] = response.parsed
                if output is None and hasattr(response, "text") and response.text:
                    try:
                        raw_dict = json.loads(response.text)
                        output = _VisionClassificationOutput.model_validate(raw_dict)
                    except Exception as parse_err:
                        logger.warning(f"Failed to parse fallback raw text: {parse_err}")

                if output:
                    doc_str = output.document_type.strip().lower()
                    try:
                        doc_type = DocumentType(doc_str)
                    except ValueError:
                        doc_type = DocumentType.UNKNOWN

                    pipeline_map = {
                        DocumentType.INVOICE: PipelineTarget.INVOICE_PIPELINE,
                        DocumentType.PURCHASE_ORDER: PipelineTarget.PO_PIPELINE,
                        DocumentType.RECEIPT: PipelineTarget.RECEIPT_PIPELINE,
                        DocumentType.UNKNOWN: PipelineTarget.MANUAL_REVIEW,
                    }

                    return ClassificationResult(
                        file_name=file_path.name,
                        file_path=str(file_path.resolve()),
                        document_type=doc_type,
                        confidence=round(output.confidence, 2),
                        tier_used="multimodal_vision",
                        reasoning=output.reasoning,
                        key_indicators=output.key_indicators,
                        suggested_pipeline=pipeline_map[doc_type],
                    )

            except Exception as call_err:
                if attempt == max_retries:
                    logger.error(f"[Tier 2] Final retry limit reached ({max_retries}) for '{file_path.name}': {call_err}", exc_info=True)
                    break

                sleep_duration = base_delay * (backoff_factor ** (attempt - 1))
                if "429" in str(call_err) or "RESOURCE_EXHAUSTED" in str(call_err):
                    sleep_duration = max(sleep_duration, 20.0)
                    logger.warning(f"[Tier 2] Rate limit (429) on attempt {attempt}. Retrying '{file_path.name}' in {sleep_duration:.1f}s...")
                else:
                    logger.warning(f"[Tier 2] API error on attempt {attempt}: {call_err}. Retrying in {sleep_duration:.1f}s...")
                time.sleep(sleep_duration)

    except Exception as err:
        logger.error(f"[Tier 2] Multimodal classification failed for '{file_path.name}': {err}", exc_info=True)
    finally:
        if uploaded_file and hasattr(uploaded_file, "name"):
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                pass

    # Safe fallback if API call fails
    return ClassificationResult(
        file_name=file_path.name,
        file_path=str(file_path.resolve()),
        document_type=DocumentType.UNKNOWN,
        confidence=0.0,
        tier_used="multimodal_vision_failed",
        reasoning="Multimodal vision processing encountered an error or unreadable document.",
        key_indicators=[],
        suggested_pipeline=PipelineTarget.MANUAL_REVIEW,
    )


def classify_document(
    document: Union[str, Path, IngestedDocument],
    client: Optional[genai.Client] = None
) -> ClassificationResult:
    """
    Main Classification Entry Point:
    Accepts a file path or an already IngestedDocument.
    1. Runs Tier 1 (instant local text heuristics on digital text).
    2. If Tier 1 is indeterminate or file is an image/scanned PDF, runs Tier 2 (Gemini Vision).
    """
    if isinstance(document, IngestedDocument):
        doc = document
    else:
        path = Path(document).resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Target document file not found: {path}")
        doc = ingest_document(path, extract_text=True)

    path = doc.file_path
    if doc.extension.lower() not in SUPPORTED_EXTENSIONS and doc.extension.lower() not in (".csv", ".tsv", ".json", ".log", ".bmp", ".tiff"):
        return ClassificationResult(
            file_name=doc.file_name,
            file_path=str(path),
            document_type=DocumentType.UNKNOWN,
            confidence=0.0,
            tier_used="unsupported_format",
            reasoning=f"Unsupported file format '{doc.extension}'.",
            key_indicators=[],
            suggested_pipeline=PipelineTarget.MANUAL_REVIEW,
        )

    if doc.file_size_bytes > MAX_FILE_SIZE_BYTES:
        return ClassificationResult(
            file_name=doc.file_name,
            file_path=str(path),
            document_type=DocumentType.UNKNOWN,
            confidence=0.0,
            tier_used="size_limit_exceeded",
            reasoning=f"File exceeds maximum allowed size of {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB.",
            key_indicators=[],
            suggested_pipeline=PipelineTarget.MANUAL_REVIEW,
        )

    # ------------------------------------------------------------
    # Tier 1: Check Local Text Heuristics (Instant, 0 API cost)
    # ------------------------------------------------------------
    if doc.has_text and doc.text_content:
        text_result = classify_text_heuristics(doc.text_content, path)
        if text_result and text_result.confidence >= 0.85:
            return text_result

    # ------------------------------------------------------------
    # Tier 2: Multimodal Vision Fallback (Images & Scanned PDFs)
    # ------------------------------------------------------------
    if client is None:
        client = get_gemini_client()

    if client:
        return classify_multimodal_vision(client, path)

    # If Gemini client unavailable and text heuristics failed
    return ClassificationResult(
        file_name=doc.file_name,
        file_path=str(path),
        document_type=DocumentType.UNKNOWN,
        confidence=0.0,
        tier_used="no_client_available",
        reasoning="Document text insufficient for local classification and Gemini client unavailable for vision.",
        key_indicators=[],
        suggested_pipeline=PipelineTarget.MANUAL_REVIEW,
    )



def classify_and_organize_directory(
    input_dir: Optional[Union[str, Path]] = None,
    output_dir: Optional[Union[str, Path]] = None,
    mode: str = "report",
    client: Optional[genai.Client] = None,
) -> BatchClassificationReport:
    """
    Scans an input directory containing mixed business documents, classifies each file,
    and optionally routes / organizes them into category subdirectories:
      - invoices/
      - purchase_orders/
      - receipts/
      - unknown/

    Parameters:
      input_dir: Source folder with mixed files (defaults to dataset/inbox).
      output_dir: Destination folder to place organized documents and report (defaults to dataset/organized).
      mode: 'report' (default, classify only), 'copy' (copy to category folder), 'move' (move to category folder).
      client: Optional genai.Client instance.
    """
    if input_dir is None:
        input_dir = DEFAULT_INBOX_DIR

    in_path = Path(input_dir).resolve()
    if not in_path.exists():
        in_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created default inbox directory: {in_path}")

    if not in_path.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {in_path}")

    if output_dir is None and mode in {"copy", "move"}:
        output_dir = DEFAULT_ORGANIZED_DIR

    if client is None:
        client = get_gemini_client()

    files = sorted([
        f for f in in_path.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ])

    logger.info(f"Scanning directory '{in_path.name}': Found {len(files)} candidate document files.")
    start_time = time.time()

    results: List[ClassificationResult] = []
    counts: Dict[str, int] = {
        DocumentType.INVOICE.value: 0,
        DocumentType.PURCHASE_ORDER.value: 0,
        DocumentType.RECEIPT.value: 0,
        DocumentType.UNKNOWN.value: 0,
    }

    # Setup target subdirectories if organizing
    out_path = Path(output_dir).resolve() if output_dir else None
    if out_path and mode in {"copy", "move"}:
        for cat in ["invoices", "purchase_orders", "receipts", "unknown"]:
            (out_path / cat).mkdir(parents=True, exist_ok=True)

    folder_map = {
        DocumentType.INVOICE: "invoices",
        DocumentType.PURCHASE_ORDER: "purchase_orders",
        DocumentType.RECEIPT: "receipts",
        DocumentType.UNKNOWN: "unknown",
    }

    for idx, f in enumerate(files, 1):
        res = classify_document(f, client=client)
        results.append(res)
        counts[res.document_type.value] = counts.get(res.document_type.value, 0) + 1

        # File organization
        if out_path and mode in {"copy", "move"}:
            dest_dir = out_path / folder_map[res.document_type]
            dest_file = dest_dir / f.name
            if mode == "copy":
                shutil.copy2(f, dest_file)
            elif mode == "move":
                shutil.move(str(f), str(dest_file))

        tier_tag = "[T1:Text]" if res.tier_used == "local_text" else "[T2:Vision]"
        logger.info(
            f"[{idx:4d}/{len(files):4d}] {tier_tag} {f.name:<32} -> "
            f"{res.document_type.value.upper():<14} (Conf: {res.confidence * 100:5.1f}%)"
        )

        # Rate limit pacing for multimodal calls
        if res.tier_used == "multimodal_vision" and idx < len(files):
            time.sleep(3.5)

    elapsed = time.time() - start_time
    report = BatchClassificationReport(
        total_files=len(files),
        counts=counts,
        processing_time_seconds=round(elapsed, 2),
        results=results,
    )

    # Save report if output directory specified
    if out_path:
        out_path.mkdir(parents=True, exist_ok=True)
        report_file = out_path / "classification_report.json"
        with open(report_file, "w", encoding="utf-8") as rf:
            json.dump(report.model_dump(mode="json"), rf, indent=2)
        logger.info(f"Structured batch classification report saved to: {report_file}")

    print("\n" + "=" * 70)
    print(f"DOCUMENT CLASSIFICATION BATCH SUMMARY")
    print("=" * 70)
    print(f"Total Documents Processed : {report.total_files}")
    print(f"Invoices Identified       : {counts[DocumentType.INVOICE.value]}")
    print(f"Purchase Orders Identified: {counts[DocumentType.PURCHASE_ORDER.value]}")
    print(f"Receipts Identified       : {counts[DocumentType.RECEIPT.value]}")
    print(f"Unknown / Flagged         : {counts[DocumentType.UNKNOWN.value]}")
    print(f"Total Execution Time      : {report.processing_time_seconds:.2f}s")
    print("=" * 70 + "\n")

    return report


# ============================================================
# CLI INTERFACE
# ============================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Universal Document Classifier: Classifies mixed Invoices, POs, and Receipts."
    )
    parser.add_argument("--input-dir", "-i", type=str, default=str(DEFAULT_INBOX_DIR), help="Input directory containing mixed files (defaults to dataset/inbox).")
    parser.add_argument("--output-dir", "-o", type=str, default=str(DEFAULT_ORGANIZED_DIR), help="Output directory to save organized files / reports (defaults to dataset/organized).")
    parser.add_argument("--mode", "-m", choices=["report", "copy", "move"], default="copy", help="Organization mode: 'copy' (default), 'move', or 'report'.")

    args = parser.parse_args()
    classify_and_organize_directory(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        mode=args.mode
    )

