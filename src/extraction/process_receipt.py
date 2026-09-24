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
DATASET_DIRECTORY = PROJECT_ROOT / "dataset" / "standalone" / "receipts"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas import Receipt
from validation import verify_receipt_math
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
logger = logging.getLogger("ReceiptExtractor")

RECEIPT_EXTRACTION_PROMPT = """
You are an expert document data extraction system specializing in scanned receipts, retail slips, POS printouts, supermarket tickets, dining bills, and other transactional documents.

Your task is to extract structured information from the provided receipt document.

IMPORTANT RULES:
1. Extract ONLY information that is explicitly present in the document.
2. NEVER invent, guess, estimate, or infer missing values.
3. If a field cannot be reliably determined from the document, return null.
4. Preserve the exact meaning and values of the original document.
5. Pay special attention to numbers, decimal values, currency symbols, dates, quantities, and totals.
6. The document may be scanned, rotated, skewed, low resolution, handwritten, partially cropped, or affected by OCR noise.
7. Do not calculate missing totals or values yourself.
8. Return numeric fields as numbers/floats, never as formatted strings with currency symbols or commas.
9. Normalize all valid dates to YYYY-MM-DD when the format can be reliably determined.

FIELD-SPECIFIC INSTRUCTIONS:
- vendor_name: Extract the business/store/merchant name from the receipt header. Do not use cashier or customer names.
- receipt_number: Extract the receipt, invoice, transaction, or reference number. Prefer an explicitly labeled identifier. Do not mistake phone numbers, tax IDs, or dates for receipt_number.
- date: Extract ONLY the transaction date. Must contain a calendar date (day, month, year). DO NOT extract time-only values. Return null if ambiguous.
- currency: Standard ISO 4217 code (e.g., USD, EUR, GBP, PKR) or visible currency symbol. Return null if ambiguous.
- items: Extract each distinct purchased item separately. Keep exact descriptions.
- subtotal: The amount explicitly labeled 'Subtotal' or 'Sub Total'. Do NOT use 'Total', 'Grand Total', or 'Amount Due'. Return null if not explicitly shown.
- discount_percentage: Discount percentage explicitly printed (numeric, without %). Return null if not shown.
- discount_amount: Monetary document-level discount amount explicitly printed. Do not calculate from percentage. Return null if not shown.
- tax: Total tax amount explicitly printed (sales tax, VAT, GST). Do not calculate. Return null if not shown.
- service_charge: Service charge or gratuity amount explicitly printed (e.g. 'Service Charge 10%', 'Serv Charge', 'SVC', 'Tip'). Return the numeric monetary amount. Return null if not shown.
- rounding_adjustment: Explicit rounding adjustment (positive or negative). Return null if not shown.
- total: Final net transaction amount payable. Prefer 'Total', 'Grand Total', 'Amount Due', or 'Total Sales' (when used as the net payable amount).
  * CRITICAL FOR AMBIGUOUS 'Total : 0.00' ROWS: Some POS systems (e.g. cash sales templates) print an intermediate line labeled 'Total : 0.00' (representing tax total, balance due, or discount total) while printing 'Total Sales: 327.00' as the transaction total. NEVER extract 0.00 as the final transaction total if the receipt contains purchased items with non-zero amounts and a non-zero 'Total Sales' or payment amount is printed. In such cases, extract the actual transaction payable amount (e.g. 327.00 from Total Sales).
- total_quantity: Total quantity explicitly printed (labeled 'Total Qty'). Do not calculate by summing.

ITEM EXTRACTION RULES:
- Extract every visible line item separately.
- Do not merge multiple items into one.
- Preserve the original item description as closely as possible.
- Preserve item/product codes exactly when visible.
- quantity must represent the purchased quantity, not a number appearing elsewhere in the row.
- unit_price: Price for one unit. If an item row shows an explicit unit price marked with '@' (e.g. '@149.00' or net '@89.21'), extract that as unit_price.
- discount: Extract line-item discounts when explicitly shown underneath an item (e.g. 'Aeon card DISC -4.69', 'Item promo -20.00', '@DISC 10% -5.59'). If an item has multiple discounts listed under it, sum them into the item's total discount.
- total: Final amount for this line item. If a gross amount is printed on the item row, extract it; if an item discount appears, make sure to extract the discount in the item's discount field. If a final net price is printed with '@' (e.g. '@89.21') after discounts, extract the net amount or extract the gross amount with the discount so the net line total can be reconciled. Return null if no line total is explicitly printed on that line.
- Do not substitute subtotal, tax, discount, or grand total for line item total.
- If a value is unreadable or ambiguous, return null rather than guessing.
- If a line item exists but one of its fields is missing, still return the line item with the missing field as null.

CRITICAL INSTRUCTIONS ON MISSING TOTALS:
- DO NOT calculate, compute, multiply, or sum missing totals yourself!
- If the document does NOT explicitly print a "Total", "Grand Total", or "Subtotal" label with a corresponding printed amount, you MUST return null for total and subtotal.
- NEVER multiply quantity by unit price to invent a line total if none is printed on the row.
- NEVER sum line items to invent a subtotal or total if none is printed on the document.
"""


def _generate_with_backoff(client: genai.Client, contents: list) -> Optional[Receipt]:
    """
    Executes the Gemini API call routed across the 9-tier Gemini cascade.
    Handles transient demand spikes with exponential backoff on the same tier,
    and cascades across tiers on quota exhaustion (429/ResourceExhausted).
    """
    return route_extraction(
        client=client,
        contents=contents,
        response_schema=Receipt,
        preferred_model=MODEL_NAME,
    )


def extract_single_receipt(client: genai.Client, file_path: Path) -> Optional[Receipt]:
    """
    Validates, prepares, and parses a single receipt file (image, PDF, or text)
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
                return _generate_with_backoff(client, [RECEIPT_EXTRACTION_PROMPT, uploaded_file])
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
                logger.info(f"Reading plain text receipt: {file_path.name}")
                text_content = file_path.read_text(encoding="utf-8", errors="replace")
                return _generate_with_backoff(
                    client, [RECEIPT_EXTRACTION_PROMPT, f"DOCUMENT TEXT:\n{text_content}"]
                )
            except Exception as txt_err:
                logger.error(f"Failed to read text file '{file_path.name}': {txt_err}", exc_info=True)
                return None

        else:
            try:
                with Image.open(file_path) as img:
                    img.verify()

                with Image.open(file_path) as img:
                    return _generate_with_backoff(client, [RECEIPT_EXTRACTION_PROMPT, img])
            except UnidentifiedImageError:
                logger.error(f"Cannot identify or read image '{file_path.name}'. File may be corrupt.")
                return None

    except Exception as general_err:
        logger.error(f"Unexpected error processing '{file_path.name}': {general_err}", exc_info=True)
        return None


def process_receipt_batch(directory_path: Path) -> List[dict]:
    """
    Scans a directory for supported receipt files, extracts structured data,
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
            receipt_data = extract_single_receipt(client, file_path)

            if receipt_data:
                record = {
                    "file_name": file_path.name,
                    "file_path": str(file_path),
                    "extracted_data": receipt_data.model_dump(mode="json")
                }
                successful_extractions.append(record)
                print(receipt_data.model_dump_json(indent=2))
            else:
                logger.warning(f"STATUS: FAILED TO EXTRACT -> {file_path.name}")

        except Exception as loop_err:
            logger.error(f"Unhandled exception during batch loop for '{file_path.name}': {loop_err}", exc_info=True)
            continue

    print(f"\n{'=' * 70}")
    print(f"BATCH COMPLETE: {len(successful_extractions)}/{total_files} successfully parsed.")
    print(f"{'=' * 70}\n")

    return successful_extractions


def process_and_validate_single_receipt(client: genai.Client, file_path: Path) -> Optional[dict]:
    """
    Stage 1: Extracts structured data from a single receipt file.
    Stage 2: Deterministically validates the extracted data against arithmetic and schema rules.
    """
    logger.info(f"--- Processing single receipt: {file_path.name} ---")
    receipt_data = extract_single_receipt(client, file_path)
    if not receipt_data:
        logger.warning(f"Extraction failed for: {file_path.name}")
        return None

    extracted_dict = receipt_data.model_dump(mode="json")
    val_report = verify_receipt_math(extracted_dict)
    val_report["file_name"] = file_path.name
    val_report["file_path"] = str(file_path)
    val_report["receipt_number"] = receipt_data.receipt_number

    return {
        "file_name": file_path.name,
        "file_path": str(file_path),
        "receipt_data": receipt_data,
        "extracted_data": extracted_dict,
        "validation_report": val_report
    }


def run_receipt_pipeline(directory_path: Path = DATASET_DIRECTORY) -> List[dict]:
    """
    Orchestrates the two-stage receipt workflow:
      Stage 1: Batch receipt extraction using the Gemini multimodal model.
      Stage 2: Deterministic verification and mathematical validation of all extracted receipts.
    """
    print("\n" + "=" * 70)
    print("STAGE 1: RECEIPT EXTRACTION")
    print("=" * 70)

    extracted_records = process_receipt_batch(directory_path)

    if not extracted_records:
        logger.warning("No receipt records extracted. Skipping Stage 2 validation.")
        return []

    print("\n" + "=" * 70)
    print("STAGE 2: RECEIPT VALIDATION")
    print("=" * 70)

    validated_records = []
    for record in extracted_records:
        payload = record.get("extracted_data", record)
        val_report = verify_receipt_math(payload)
        record["validation_report"] = val_report
        validated_records.append(record)

    return validated_records


if __name__ == "__main__":
    DATASET_DIRECTORY.mkdir(parents=True, exist_ok=True)
    results = run_receipt_pipeline(DATASET_DIRECTORY)