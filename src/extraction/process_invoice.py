import os, sys
import time
import logging
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
load_dotenv()  # Load environment variables before accessing os.environ

from google import genai
from google.genai import types
from PIL import Image, UnidentifiedImageError

# Import the schema from your invoice module

# ==========================================
# GLOBAL PATH CONFIGURATION
# ==========================================
# Dynamically resolve the absolute path to ONE LEVEL ABOVE the directory containing this script[cite: 2]
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_ROOT = Path(__file__).resolve().parent.parent
# Construct production-grade paths relative to the project root[cite: 2]
DATASET_DIRECTORY = PROJECT_ROOT / "dataset" / "standalone" / "invoices"

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
logger = logging.getLogger("InvoiceExtractor")

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
from schemas import Invoice
from validation import verify_invoice_math
from agent.router import route_extraction

INVOICE_EXTRACTION_PROMPT = """
You are an expert document extraction system specialized in accounts payable, billing documents, and invoices.

Your task is to accurately extract structured information from the provided document into the requested schema.

CORE RULES:
1. Extract ONLY information that is explicitly stated on the invoice.
2. NEVER guess, estimate, or hallucinate missing information.
3. If any field is missing or ambiguous, return null (None).
4. Preserve values exactly as shown. Do not reformat text or change wording unless formatting a date or currency code.
5. All dates must be converted to ISO format (YYYY-MM-DD) when clear. Return null if ambiguous.
6. Currency should be the standard 3-letter ISO 4217 code (e.g., USD, EUR, GBP). Do not guess if unclear.
7. Return monetary values and line item quantities as pure numbers or decimals; do not include currency symbols or comma separators.
8. Do not manually calculate missing totals or line totals if they are omitted from the document.

DOCUMENT DISCRIMINATION:
- invoice_number: Must be the invoice identifier, NOT a purchase order number, quote number, or account ID.
- vendor: The company/seller issuing the invoice and requesting payment.
- buyer: The customer/entity being billed.
- items: Extract every distinct line item in the exact order shown. Capture unit_price, quantity, discount, tax, and line_total when present.
- subtotal, discount, shipping, tax, total: Distinct document-level summary values. Do not merge line-item taxes/discounts with invoice-level totals.
- invoice_status: Only extract if explicitly printed (e.g., 'Paid', 'Overdue', 'Draft').
"""

def _generate_with_exponential_backoff(
    client: genai.Client, contents: list
) -> Optional[Invoice]:
    """
    Executes the Gemini API call routed across the 9-tier Gemini cascade.
    Handles transient demand spikes with exponential backoff on the same tier,
    and cascades across tiers on quota exhaustion (429/ResourceExhausted).
    """
    return route_extraction(
        client=client,
        contents=contents,
        response_schema=Invoice,
        preferred_model=MODEL_NAME,
    )

def extract_single_invoice(client: genai.Client, file_path: Path) -> Optional[Invoice]:
    """
    Validates, prepares, and parses a single invoice file (PDF or image)
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
            # Native PDF handling via Gemini File API
            uploaded_file = None
            try:
                logger.info(f"Uploading PDF document to Gemini File API: {file_path.name}")
                uploaded_file = client.files.upload(file=str(file_path))
                
                return _generate_with_exponential_backoff(
                    client, [INVOICE_EXTRACTION_PROMPT, uploaded_file]
                )
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
            # Plain text document handling
            try:
                logger.info(f"Reading plain text document: {file_path.name}")
                text_content = file_path.read_text(encoding="utf-8", errors="replace")
                return _generate_with_exponential_backoff(
                    client, [INVOICE_EXTRACTION_PROMPT, f"DOCUMENT TEXT:\n{text_content}"]
                )
            except Exception as txt_err:
                logger.error(f"Failed to read text file '{file_path.name}': {txt_err}", exc_info=True)
                return None

        else:
            # Standard image handling via PIL
            try:
                with Image.open(file_path) as img:
                    img.verify()  # Check for corruption without loading pixels fully
                
                with Image.open(file_path) as img:
                    return _generate_with_exponential_backoff(
                        client, [INVOICE_EXTRACTION_PROMPT, img]
                    )
            except UnidentifiedImageError:
                logger.error(f"Cannot identify or read image '{file_path.name}'. File may be corrupt.")
                return None


    except Exception as general_err:
        logger.error(f"Unexpected error processing '{file_path.name}': {general_err}", exc_info=True)
        return None

def process_invoice_batch(directory_path: Path) -> List[dict]:
    """
    Scans a directory for supported invoice files, extracts structured data,
    and returns a list of successfully parsed records.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.critical("GEMINI_API_KEY environment variable is not configured. Aborting batch.")
        return []

    try:
        if not directory_path.exists() or not directory_path.is_dir():
            logger.error(f"Target directory does not exist or is not a valid directory: {directory_path}")
            return []

        # Iterate safely through the global path
        target_files = [
            f for f in directory_path.iterdir()
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        ]

        total_files = len(target_files)
        if total_files == 0:
            logger.warning(f"No supported invoice files (.pdf, .jpg, etc.) found in: {directory_path}")
            return []

        logger.info(f"Found {total_files} file(s) for extraction in: {directory_path}")
        client = genai.Client(api_key=api_key)
        successful_records = []

        for index, file_path in enumerate(target_files, start=1):
            border = "=" * 70
            print(f"\n{border}")
            print(f"[{index}/{total_files}] PROCESSING: {file_path.name}")
            print(f"{border}\n")

            try:
                invoice_data = extract_single_invoice(client, file_path)

                if invoice_data:
                    # Model dump to Python primitives
                    record = {
                        "file_name": file_path.name,
                        "file_path": str(file_path),
                        "extracted_data": invoice_data.model_dump(mode="json")
                    }
                    successful_records.append(record)
                    print(invoice_data.model_dump_json(indent=2))
                else:
                    logger.warning(f"FAILED TO EXTRACT: {file_path.name}")

            except Exception as loop_err:
                logger.error(f"Unhandled exception during batch loop for '{file_path.name}': {loop_err}", exc_info=True)
                continue

        print(f"\n{'=' * 70}")
        print(f"BATCH COMPLETE: {len(successful_records)}/{total_files} successfully parsed.")
        print(f"{'=' * 70}\n")

        return successful_records

    except Exception as batch_err:
        logger.critical(f"Critical failure during batch processing: {batch_err}", exc_info=True)
        return []


def process_and_validate_single_invoice(client: genai.Client, file_path: Path) -> Optional[dict]:
    """
    Stage 1: Extracts structured data from a single invoice file.
    Stage 2: Deterministically validates the extracted data against arithmetic and schema rules.
    """
    logger.info(f"--- Processing single invoice: {file_path.name} ---")
    invoice_data = extract_single_invoice(client, file_path)
    if not invoice_data:
        logger.warning(f"Extraction failed for: {file_path.name}")
        return None

    extracted_dict = invoice_data.model_dump(mode="json")
    val_report = verify_invoice_math(extracted_dict)
    val_report["file_name"] = file_path.name
    val_report["file_path"] = str(file_path)
    val_report["invoice_number"] = invoice_data.invoice_number

    return {
        "file_name": file_path.name,
        "file_path": str(file_path),
        "invoice_data": invoice_data,
        "extracted_data": extracted_dict,
        "validation_report": val_report
    }


def run_invoice_pipeline(directory_path: Path = DATASET_DIRECTORY) -> List[dict]:
    """
    Orchestrates the two-stage invoice workflow:
      Stage 1: Batch invoice extraction using the Gemini multimodal model.
      Stage 2: Deterministic verification and mathematical validation of all extracted invoices.
    """
    print("\n" + "=" * 70)
    print("STAGE 1: INVOICE EXTRACTION")
    print("=" * 70)

    extracted_records = process_invoice_batch(directory_path)

    if not extracted_records:
        logger.warning("No invoice records extracted. Skipping Stage 2 validation.")
        return []

    print("\n" + "=" * 70)
    print("STAGE 2: INVOICE VALIDATION")
    print("=" * 70)

    validated_records = []
    for record in extracted_records:
        payload = record.get("extracted_data", record)
        val_report = verify_invoice_math(payload)
        record["validation_report"] = val_report
        validated_records.append(record)

    return validated_records


if __name__ == "__main__":
    # Ensure the dynamic path is created if it does not exist
    DATASET_DIRECTORY.mkdir(parents=True, exist_ok=True)
    
    # Execute Stage 1: Extraction, followed by Stage 2: Validation
    results = run_invoice_pipeline(DATASET_DIRECTORY)