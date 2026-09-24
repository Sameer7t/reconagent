import os
import sys
import shutil
import tempfile
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# ============================================================
# PATH SETUP & CONFIGURATION
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
DATASET_INVOICES_DIR = PROJECT_ROOT / "dataset" / "standalone" / "invoices"

# Ensure src is in sys.path
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Load .env file from project root
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

from google import genai
from schemas import Invoice
from extraction import (
    extract_single_invoice,
    process_invoice_batch,
    process_and_validate_single_invoice
)
from validation import verify_invoice_math

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("TestInvoicePipeline")


def get_gemini_client() -> genai.Client:
    """Initializes and returns the Gemini API client from environment variables."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY environment variable is not set. "
            "Please configure it in the .env file at the project root."
        )
    return genai.Client(api_key=api_key)


def get_default_sample_invoice() -> Path:
    """Finds the first available invoice file in the dataset directory."""
    if not DATASET_INVOICES_DIR.exists():
        raise FileNotFoundError(f"Dataset directory not found: {DATASET_INVOICES_DIR}")

    sample_files = sorted(
        [f for f in DATASET_INVOICES_DIR.iterdir() if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".pdf"}]
    )
    if not sample_files:
        raise FileNotFoundError(f"No invoice images or PDFs found in: {DATASET_INVOICES_DIR}")

    return sample_files[0]


def test_single_invoice_extract_and_validate(invoice_path: Optional[Path] = None):
    """
    Test 1: Single Invoice End-to-End Test
    1. Runs extraction using extract_single_invoice() from src/extraction/process_invoice.py
    2. Takes the extracted structured data and validates it using verify_invoice_math() from src/validation/invoice_validation.py
    3. Asserts the validity of both stages.
    """
    if invoice_path is None:
        invoice_path = get_default_sample_invoice()

    print("\n" + "=" * 80)
    print(f"TEST 1: SINGLE INVOICE EXTRACTION -> VALIDATION PIPELINE")
    print(f"Target File: {invoice_path.name}")
    print("=" * 80)

    # ---------------------------------------------------------
    # STAGE 1: EXTRACTION (from src/extraction/process_invoice.py)
    # ---------------------------------------------------------
    client = get_gemini_client()
    logger.info(f"[STAGE 1] Extracting structured data from {invoice_path.name}...")

    extracted_invoice: Optional[Invoice] = extract_single_invoice(client, invoice_path)

    assert extracted_invoice is not None, f"Extraction failed for {invoice_path.name}"
    assert isinstance(extracted_invoice, Invoice), (
        f"Expected instance of Invoice schema, got {type(extracted_invoice)}"
    )
    assert extracted_invoice.invoice_number is not None, "Extracted invoice is missing invoice_number"
    assert isinstance(extracted_invoice.items, list), "Extracted invoice items must be a list"

    print("\n--- [STAGE 1 SUCCESS] Extracted Invoice Data ---")
    print(f"Invoice Number : {extracted_invoice.invoice_number}")
    print(f"Vendor Name    : {extracted_invoice.vendor.name if extracted_invoice.vendor else 'N/A'}")
    print(f"Buyer Name     : {extracted_invoice.buyer.name if extracted_invoice.buyer else 'N/A'}")
    print(f"Line Items Qty : {len(extracted_invoice.items)}")
    print(f"Subtotal       : {extracted_invoice.subtotal}")
    print(f"Total Tax      : {extracted_invoice.total_tax}")
    print(f"Total Discount : {extracted_invoice.total_discount}")
    print(f"Grand Total    : {extracted_invoice.total}")

    # Convert Pydantic model to dictionary for verification
    extracted_data_dict = extracted_invoice.model_dump(mode="json")

    # ---------------------------------------------------------
    # STAGE 2: VALIDATION (from src/validation/invoice_validation.py)
    # ---------------------------------------------------------
    logger.info("[STAGE 2] Running deterministic mathematical verification...")

    validation_report = verify_invoice_math(extracted_data_dict)

    # Assertions on the validation report structure
    assert isinstance(validation_report, dict), "Validation report must be a dictionary"
    assert "is_valid" in validation_report, "Validation report missing 'is_valid' boolean flag"
    assert "confidence_score" in validation_report, "Validation report missing 'confidence_score'"
    assert "checks" in validation_report, "Validation report missing 'checks' dictionary"
    assert "discrepancies" in validation_report, "Validation report missing 'discrepancies' list"
    assert "resolved_totals" in validation_report, "Validation report missing 'resolved_totals'"

    # Score bounds check
    assert 0.0 <= validation_report["confidence_score"] <= 100.0, (
        f"Invalid confidence score: {validation_report['confidence_score']}"
    )

    print("\n--- [STAGE 2 SUCCESS] Invoice Validation Report ---")
    print(f"Is Mathematically Valid : {validation_report['is_valid']}")
    print(f"Confidence Score        : {validation_report['confidence_score']}%")
    print(f"Checks Performed        : {validation_report['checks']}")
    print(f"Discrepancies Found     : {validation_report['discrepancies'] if validation_report['discrepancies'] else 'None'}")
    print(f"Resolved Totals         : {validation_report['resolved_totals']}")

    print("\n>>> TEST 1 PASSED: Extraction -> Validation pipeline succeeded.")
    return extracted_data_dict, validation_report


def test_batch_extract_and_validate(max_sample_files: int = 2):
    """
    Test 2: Batch Invoice Extraction and Validation Workflow
    1. Prepares a controlled sample folder with 1-2 invoice files to test batching without wasting API quota.
    2. Runs process_invoice_batch() from src/extraction/process_invoice.py.
    3. Feeds extracted records to verify_invoice_batch() from src/validation/invoice_validation.py.
    4. Prints and asserts summary reports.
    """
    print("\n" + "=" * 80)
    print(f"TEST 2: BATCH INVOICE EXTRACTION -> VALIDATION PIPELINE")
    print(f"Sampling {max_sample_files} invoice(s) for controlled batch execution")
    print("=" * 80)

    # Pick sample files from dataset
    all_files = sorted(
        [f for f in DATASET_INVOICES_DIR.iterdir() if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".pdf"}]
    )
    sample_files = all_files[:max_sample_files]
    assert len(sample_files) > 0, "No sample invoices available for batch testing"

    # Use a temporary directory containing only the sample invoices to test batching safely
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        for f in sample_files:
            shutil.copy(f, temp_dir / f.name)

        # ---------------------------------------------------------
        # STAGE 1: BATCH EXTRACTION (from src/extraction/process_invoice.py)
        # ---------------------------------------------------------
        logger.info(f"[STAGE 1] Running process_invoice_batch on {len(sample_files)} sample files...")
        extracted_batch_records = process_invoice_batch(temp_dir)

        assert len(extracted_batch_records) >= int(len(sample_files) * 0.95), (
            f"Expected at least 95% extracted records, got {len(extracted_batch_records)}/{len(sample_files)}"
        )


        for record in extracted_batch_records:
            assert "file_name" in record
            assert "file_path" in record
            assert "extracted_data" in record
            assert isinstance(record["extracted_data"], dict)

        print(f"\n[STAGE 1 SUCCESS] Successfully extracted {len(extracted_batch_records)} invoice records.")

        # ---------------------------------------------------------
        # STAGE 2: BATCH VALIDATION (from src/validation/invoice_validation.py)
        # ---------------------------------------------------------
        logger.info("[STAGE 2] Running verify_invoice_math on extracted records...")
        audited_batch_records = []
        for record in extracted_batch_records:
            val_report = verify_invoice_math(record["extracted_data"])
            rec_copy = dict(record)
            rec_copy["validation_report"] = val_report
            audited_batch_records.append(rec_copy)

        assert len(audited_batch_records) == len(extracted_batch_records)

        for record in audited_batch_records:
            assert "validation_report" in record, "Audited record missing 'validation_report'"
            val_report = record["validation_report"]
            assert "is_valid" in val_report
            assert "confidence_score" in val_report
            assert "discrepancies" in val_report

        print("\n[STAGE 2 SUCCESS] Audited batch records:")
        for idx, r in enumerate(audited_batch_records, start=1):
            vr = r["validation_report"]
            print(f"[{idx}] {r['file_name']} -> Valid: {vr['is_valid']}, Score: {vr['confidence_score']}%")

    print(">>> TEST 2 PASSED: Batch Extraction -> Validation workflow succeeded.")
    return audited_batch_records


def test_integrated_single_invoice_helper():
    """
    Test 3: Tests the integrated helper process_and_validate_single_invoice()
    from src/extraction/process_invoice.py which encapsulates both stages into a single call.
    """
    sample_file = get_default_sample_invoice()

    print("\n" + "=" * 80)
    print("TEST 3: INTEGRATED SINGLE INVOICE HELPER (process_and_validate_single_invoice)")
    print(f"Target File: {sample_file.name}")
    print("=" * 80)

    client = get_gemini_client()
    result = process_and_validate_single_invoice(client, sample_file)

    assert result is not None, "process_and_validate_single_invoice returned None"
    assert "file_name" in result
    assert "extracted_data" in result
    assert "validation_report" in result
    assert isinstance(result["validation_report"], dict)
    assert "confidence_score" in result["validation_report"]

    print("\nResult Keys:", list(result.keys()))
    print(f"File: {result['file_name']}")
    print(f"Invoice No: {result['validation_report'].get('invoice_number')}")
    print(f"Validation Score: {result['validation_report']['confidence_score']}%")
    print(f"Status: {'VALID' if result['validation_report']['is_valid'] else 'INVALID'}")

    print("\n>>> TEST 3 PASSED: Integrated helper function verified.")
    return result


if __name__ == "__main__":
    print("\n" + "#" * 80)
    print("STARTING END-TO-END INVOICE EXTRACTION & VALIDATION PIPELINE TESTS")
    print("#" * 80)

    try:
        # 1. Single invoice extraction followed by validation
        # test_single_invoice_extract_and_validate()

        # 2. Integrated single invoice helper
        # test_integrated_single_invoice_helper()

        # 3. Controlled batch extraction followed by batch validation
        test_batch_extract_and_validate(max_sample_files=500)

        print("\n" + "#" * 80)
        print("ALL EXTRACTION & VALIDATION INTEGRATION TESTS COMPLETED SUCCESSFULLY!")
        print("#" * 80 + "\n")

    except Exception as err:
        logger.critical(f"Test suite encountered an error: {err}", exc_info=True)
        sys.exit(1)
