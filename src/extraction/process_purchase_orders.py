import os
import sys
import time
import json
import logging
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv()  # Execute before accessing os.environ

from google import genai
from google.genai import types
from PIL import Image, UnidentifiedImageError

# ==========================================
# GLOBAL PATH CONFIGURATION
# ==========================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIRECTORY = PROJECT_ROOT / "dataset" / "standalone" / "purchase_orders"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas import PurchaseOrder
from validation import verify_purchase_order_math
from agent.router import route_extraction

# ==========================================
# EXTRACTION CONSTANTS
# ==========================================
MODEL_NAME = "gemini-3.5-flash-lite"
MAX_FILE_SIZE_MB = 25
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".txt"}

# Exponential Backoff Configuration
MAX_RETRIES = 5
BASE_DELAY_SECONDS = 2
BACKOFF_FACTOR = 2.0

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("POExtractor")

PO_EXTRACTION_PROMPT = """
You are an expert document data extraction system specializing in purchase orders, vendor agreements, and procurement forms.

Your task is to extract structured information from the provided purchase order document.

IMPORTANT RULES:
1. Extract ONLY information that is explicitly present in the document.
2. NEVER invent, guess, estimate, or infer missing values.
3. If a field cannot be reliably determined from the document, return null.
4. Preserve the exact meaning and values of the original document.
5. Pay special attention to numbers, decimal values, ISO currency codes, dates, quantities, and totals.
6. The document may be scanned, rotated, skewed, low resolution, multi-page, or affected by OCR noise.
7. Do not calculate missing totals or values yourself.
8. Return numeric fields as numbers/floats, never as formatted strings with currency symbols or commas.
9. Normalize all valid dates to YYYY-MM-DD.

FIELD-SPECIFIC INSTRUCTIONS:
- purchase_order_number: Extract the unique PO number. Do NOT confuse it with an invoice number.
- order_date: The date on which the purchase order was issued (YYYY-MM-DD).
- delivery_date: Expected or requested delivery date (YYYY-MM-DD). Return null if not stated.
- vendor_name & vendor_address: Identify the supplier/vendor receiving the purchase order.
- buyer_name & buyer_address: Identify the purchasing organization or buyer issuing the order.
- currency: Standard ISO 4217 code (e.g., USD, EUR, GBP, PKR). Return null if ambiguous.
- items: Extract each distinct product/service line item. Keep exact descriptions and codes.
- subtotal, discount, shipping, tax, rounding_adjustment, total: Distinguish clearly between document-level adjustments and line-item values.
- payment_terms & delivery_terms: Extract commercial conditions.
- notes: Any special instructions or handling notes not fitting other fields.

ITEM EXTRACTION RULES:
- Extract every visible line item separately.
- Do not merge multiple line items into one item.
- Preserve the original product/service description as closely as possible.
- Preserve product/SKU/item codes exactly when visible.
- quantity must represent the ordered quantity, not a number appearing elsewhere in the row.
- unit_price must represent the price for one unit.
- line_total must represent the total for that line only. Return null if no line total is explicitly printed on that line.
- Do not substitute subtotal, tax, discount, or grand total for line_total.
- If a value is unreadable or ambiguous, return null rather than guessing.
- If a line item exists but one of its fields is missing, still return the line item with the missing field as null.

CRITICAL INSTRUCTIONS ON MISSING TOTALS:
- DO NOT calculate, compute, multiply, or sum missing totals yourself!
- If the document does NOT explicitly print a "Total", "Grand Total", or "Subtotal" label with a corresponding printed amount, you MUST return null for total and subtotal.
- NEVER multiply quantity by unit price to invent a line_total if none is printed on the row.
- NEVER sum line items to invent a subtotal or total if none is printed on the document.
"""


def _generate_with_backoff(client: genai.Client, contents: list) -> Optional[PurchaseOrder]:
    """
    Executes the Gemini API call routed across the 9-tier Gemini cascade.
    Handles transient demand spikes with exponential backoff on the same tier,
    and cascades across tiers on quota exhaustion (429/ResourceExhausted).
    """
    return route_extraction(
        client=client,
        contents=contents,
        response_schema=PurchaseOrder,
        preferred_model=MODEL_NAME,
    )


def extract_single_purchase_order(client: genai.Client, file_path: Path) -> Optional[PurchaseOrder]:
    """
    Validates, prepares, and parses a single purchase order file (PDF, image, or text)
    with strict exception containment.
    """
    try:
        if not file_path.exists() or not file_path.is_file():
            logger.error(f"File path does not exist or is invalid: {file_path}")
            return None

        file_size = file_path.stat().st_size
        if file_size > MAX_FILE_SIZE_BYTES:
            logger.error(
                f"Skipping '{file_path.name}': Size ({file_size / (1024 * 1024):.2f} MB) "
                f"exceeds allowed limit ({MAX_FILE_SIZE_MB} MB)."
            )
            return None

        file_ext = file_path.suffix.lower()

        if file_ext == ".pdf":
            uploaded_file = None
            try:
                logger.info(f"Uploading PDF document to Gemini File API: {file_path.name}")
                uploaded_file = client.files.upload(file=str(file_path))
                return _generate_with_backoff(client, [PO_EXTRACTION_PROMPT, uploaded_file])
            except Exception as upload_err:
                logger.error(f"File API upload failed for '{file_path.name}': {upload_err}", exc_info=True)
                return None
            finally:
                if uploaded_file and hasattr(uploaded_file, "name"):
                    try:
                        client.files.delete(name=uploaded_file.name)
                        logger.info(f"Successfully deleted temporary remote file: {uploaded_file.name}")
                    except Exception as cleanup_err:
                        logger.warning(f"Failed to delete remote file '{uploaded_file.name}': {cleanup_err}")

        elif file_ext == ".txt":
            try:
                logger.info(f"Reading plain text purchase order: {file_path.name}")
                text_content = file_path.read_text(encoding="utf-8", errors="replace")
                return _generate_with_backoff(
                    client, [PO_EXTRACTION_PROMPT, f"DOCUMENT TEXT:\n{text_content}"]
                )
            except Exception as txt_err:
                logger.error(f"Failed to read text file '{file_path.name}': {txt_err}", exc_info=True)
                return None

        else:
            try:
                with Image.open(file_path) as img:
                    img.verify()

                with Image.open(file_path) as img:
                    return _generate_with_backoff(client, [PO_EXTRACTION_PROMPT, img])
            except UnidentifiedImageError:
                logger.error(f"Cannot identify or read image '{file_path.name}'. File may be corrupt.")
                return None

    except Exception as general_err:
        logger.error(f"Unexpected error processing '{file_path.name}': {general_err}", exc_info=True)
        return None


def process_purchase_order_batch(directory_path: Path) -> List[dict]:
    """
    Scans a directory for supported purchase order files, extracts structured data,
    and returns a list of successfully parsed records.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.critical("GEMINI_API_KEY environment variable is missing. Halting execution.")
        return []

    target_dir = Path(directory_path).resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        logger.error(f"Target directory does not exist or is not a valid directory: {target_dir}")
        return []

    target_files = [
        f for f in target_dir.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    total_files = len(target_files)
    if total_files == 0:
        logger.warning(f"No valid files found in: {target_dir}")
        return []

    logger.info(f"Discovered {total_files} candidate files in {target_dir}")

    client = genai.Client(api_key=api_key)
    successful_extractions = []

    for index, file_path in enumerate(target_files, start=1):
        separator = "=" * 70
        print(f"\n{separator}")
        print(f"[{index}/{total_files}] PROCESSING: {file_path.name}")
        print(f"{separator}\n")

        try:
            po_data = extract_single_purchase_order(client, file_path)

            if po_data:
                record = {
                    "file_name": file_path.name,
                    "file_path": str(file_path),
                    "extracted_data": po_data.model_dump(mode="json")
                }
                successful_extractions.append(record)
                print(po_data.model_dump_json(indent=2))
            else:
                logger.warning(f"STATUS: FAILED TO EXTRACT -> {file_path.name}")

        except Exception as loop_err:
            logger.error(f"Unhandled exception during batch loop for '{file_path.name}': {loop_err}", exc_info=True)
            continue

    print(f"\n{'=' * 70}")
    print(f"BATCH COMPLETE: {len(successful_extractions)}/{total_files} successfully parsed.")
    print(f"{'=' * 70}\n")

    return successful_extractions


def process_and_validate_single_purchase_order(client: genai.Client, file_path: Path) -> Optional[dict]:
    """
    Stage 1: Extracts structured data from a single purchase order file.
    Stage 2: Deterministically validates the extracted data against arithmetic and schema rules.
    """
    logger.info(f"--- Processing single purchase order: {file_path.name} ---")
    po_data = extract_single_purchase_order(client, file_path)
    if not po_data:
        logger.warning(f"Extraction failed for: {file_path.name}")
        return None

    extracted_dict = po_data.model_dump(mode="json")
    val_report = verify_purchase_order_math(extracted_dict)
    val_report["file_name"] = file_path.name
    val_report["file_path"] = str(file_path)
    val_report["purchase_order_number"] = po_data.purchase_order_number

    return {
        "file_name": file_path.name,
        "file_path": str(file_path),
        "purchase_order_data": po_data,
        "extracted_data": extracted_dict,
        "validation_report": val_report
    }


def run_purchase_order_pipeline(directory_path: Path = DATASET_DIRECTORY) -> List[dict]:
    """
    Orchestrates the two-stage purchase order workflow:
      Stage 1: Batch purchase order extraction using the Gemini multimodal model.
      Stage 2: Deterministic verification and mathematical validation of all extracted purchase orders.
    """
    print("\n" + "=" * 70)
    print("STAGE 1: PURCHASE ORDER EXTRACTION")
    print("=" * 70)

    extracted_records = process_purchase_order_batch(directory_path)

    if not extracted_records:
        logger.warning("No purchase order records extracted. Skipping Stage 2 validation.")
        return []

    print("\n" + "=" * 70)
    print("STAGE 2: PURCHASE ORDER VALIDATION")
    print("=" * 70)

    validated_records = []
    for record in extracted_records:
        payload = record.get("extracted_data", record)
        val_report = verify_purchase_order_math(payload)
        record["validation_report"] = val_report
        validated_records.append(record)

    return validated_records


if __name__ == "__main__":
    DATASET_DIRECTORY.mkdir(parents=True, exist_ok=True)
    results = run_purchase_order_pipeline(DATASET_DIRECTORY)