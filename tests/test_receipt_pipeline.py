import os
import sys
import json
import shutil
import tempfile
import logging
from decimal import Decimal
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# ============================================================
# PATH SETUP & CONFIGURATION
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
DATASET_RECEIPT_DIR = PROJECT_ROOT / "dataset" / "standalone" / "receipts"

# Ensure src is in sys.path
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Load .env file from project root
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

from google import genai
from schemas import Receipt, ReceiptItem
from extraction import (
    extract_single_receipt,
    process_receipt_batch,
    process_and_validate_single_receipt,
)
from validation import (
    verify_receipt_math,
    verify_receipt_batch,
    print_receipt_batch_validation_summary,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("TestReceiptPipeline")


def get_gemini_client() -> genai.Client:
    """Initializes and returns the Gemini API client from environment variables."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY environment variable is not set. "
            "Please configure it in the .env file at the project root."
        )
    return genai.Client(api_key=api_key)


def get_default_sample_receipt() -> Path:
    """Finds the first available receipt image in the dataset directory."""
    if not DATASET_RECEIPT_DIR.exists():
        raise FileNotFoundError(f"Dataset directory not found: {DATASET_RECEIPT_DIR}")

    sample_files = sorted(
        [f for f in DATASET_RECEIPT_DIR.iterdir()
         if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".pdf"}]
    )
    if not sample_files:
        raise FileNotFoundError(f"No receipt images or PDFs found in: {DATASET_RECEIPT_DIR}")

    return sample_files[0]


# ============================================================
# UNIT TESTS (DETERMINISTIC VERIFICATION ENGINE)
# ============================================================
def test_valid_receipt_model():
    """Unit Test 1: Receipt with accurate math passes verification at 100%."""
    receipt_data = {
        "vendor_name": "Metro Supermarket",
        "receipt_number": "REC-20260915-001",
        "items": [
            {
                "description": "Organic Milk 1L",
                "quantity": 2,
                "unit_price": 3.50,
                "discount": 0.50,
                "total": 6.50
            },
            {
                "description": "Whole Wheat Bread",
                "quantity": 1,
                "unit_price": 2.99,
                "discount": 0.00,
                "total": 2.99
            }
        ],
        "subtotal": 9.49,
        "discount_amount": 1.00,
        "tax": 0.68,
        "rounding_adjustment": -0.02,
        "total": 9.15
    }

    result = verify_receipt_math(receipt_data)
    assert result["is_valid"] is True, f"Expected valid receipt, got: {result}"
    assert result["confidence_score"] == 100.0
    assert result["checks"]["line_items_verified"] is True
    assert result["checks"]["subtotal_verified"] is True
    assert result["checks"]["grand_total_verified"] is True
    print(">>> [UNIT TEST 1 PASSED] Valid receipt verified cleanly (Score: 100.0%).")


def test_math_error_receipt():
    """Unit Test 2: Deliberate math errors cause verification failure and report discrepancies."""
    bad_receipt = {
        "vendor_name": "Quick Mart",
        "items": [
            {
                "description": "Energy Drink",
                "quantity": 3,
                "unit_price": 2.50,
                "total": 10.00  # Math error: 3 * 2.50 = 7.50
            }
        ],
        "subtotal": 10.00,
        "total": 12.00  # Grand total error: calculated 10.00 != 12.00
    }

    result = verify_receipt_math(bad_receipt)
    assert result["is_valid"] is False
    assert len(result["discrepancies"]) > 0
    print(f">>> [UNIT TEST 2 PASSED] Math error receipt correctly flagged (Score: {result['confidence_score']}%).")
    print(f"    Discrepancies: {result['discrepancies']}")


def test_missing_subtotal_reconciled():
    """Unit Test 3: Subtotal omitted passes 100% when line item sum reconciles with grand total."""
    receipt_data = {
        "vendor_name": "Corner Cafe",
        "items": [
            {"description": "Latte", "quantity": 1, "unit_price": 4.50, "total": 4.50},
            {"description": "Croissant", "quantity": 2, "unit_price": 3.00, "total": 6.00},
        ],
        "subtotal": None,
        "tax": 0.84,
        "total": 11.34  # 10.50 + 0.84 = 11.34
    }

    result = verify_receipt_math(receipt_data)
    assert result["is_valid"] is True
    assert result["confidence_score"] == 100.0
    assert result["checks"]["subtotal_verified"] is True
    assert result["checks"]["grand_total_verified"] is True
    assert len(result["discrepancies"]) == 0
    print(">>> [UNIT TEST 3 PASSED] Omitted subtotal reconciled via grand total (Score: 100.0%).")


def test_no_grand_total_receipt_passes_full_points():
    """Unit Test 4: Receipt with no grand total or subtotal awards full points without flagging."""
    receipt_data = {
        "vendor_name": "Street Vendor",
        "items": [
            {"description": "Samosa", "quantity": 5, "unit_price": 0.50, "total": 2.50},
            {"description": "Chai", "quantity": 2, "unit_price": 1.00, "total": 2.00},
        ],
        "subtotal": None,
        "total": None,
    }

    result = verify_receipt_math(receipt_data)
    assert result["is_valid"] is True, f"Expected valid receipt without totals, got: {result}"
    assert result["confidence_score"] == 100.0
    assert result["checks"]["line_items_verified"] is True
    assert result["checks"]["subtotal_verified"] is True
    assert result["checks"]["grand_total_verified"] is True
    print(">>> [UNIT TEST 4 PASSED] Receipt with no grand total awarded full points without flagging.")


def test_line_item_discount_deducted():
    """Unit Test 5: Pre-discount line total minus item discount reconciles properly with grand total."""
    receipt_data = {
        "vendor_name": "INDAH GIFT & HOME DECO",
        "items": [
            {"description": "Card", "quantity": 1, "unit_price": 10.00, "total": 10.00, "discount": None},
            {"description": "Lamp", "quantity": 1, "unit_price": 55.90, "total": 55.90, "discount": -5.59},
        ],
        "rounding_adjustment": -0.01,
        "total": 60.30,  # 10.00 + (55.90 - 5.59) - 0.01 = 60.30
    }

    result = verify_receipt_math(receipt_data)
    assert result["is_valid"] is True, f"Expected valid discounted receipt, got: {result}"
    assert result["confidence_score"] == 100.0
    assert result["checks"]["line_items_verified"] is True
    assert result["checks"]["grand_total_verified"] is True
    print(">>> [UNIT TEST 5 PASSED] Line item discount deducted cleanly (Score: 100.0%).")


def test_tax_inclusive_receipt():
    """Unit Test 6: Tax-inclusive pricing (embedded GST/VAT) validates at 100% without false surcharge flagging."""
    receipt_data = {
        "vendor_name": "Shell ISNI PETRO TRADING",
        "items": [
            {"description": "V-Power 97", "quantity": 35.10, "unit_price": 2.45, "total": 86.00}
        ],
        "tax": 4.87,  # 6% GST is embedded in 86.00
        "total": 86.00
    }

    result = verify_receipt_math(receipt_data)
    assert result["is_valid"] is True, f"Expected valid tax-inclusive receipt, got: {result}"
    assert result["confidence_score"] == 100.0
    assert result["checks"]["grand_total_verified"] is True
    assert result["resolved_totals"]["pricing_model"] == "tax_inclusive"
    assert len(result["discrepancies"]) == 0
    print(">>> [UNIT TEST 6 PASSED] Tax-inclusive (embedded GST) verified cleanly (Score: 100.0%).")


def test_service_charge_receipt():
    """Unit Test 7: Dining receipt with service charge reconciles subtotal + service charge + tax = total."""
    receipt_data = {
        "vendor_name": "Three Stooges Bistro",
        "items": [
            {"description": "HH Guiness", "quantity": 1, "unit_price": 150.00, "total": 150.00},
            {"description": "HH Tiger", "quantity": 1, "unit_price": 145.00, "total": 145.00}
        ],
        "subtotal": 295.00,
        "service_charge": 29.50,  # 10% Service Charge
        "tax": 19.47,             # 6% GST
        "rounding_adjustment": -0.02,
        "total": 343.95           # 295 + 29.50 + 19.47 - 0.02 = 343.95
    }

    result = verify_receipt_math(receipt_data)
    assert result["is_valid"] is True, f"Expected valid service charge receipt, got: {result}"
    assert result["confidence_score"] == 100.0
    assert result["checks"]["subtotal_verified"] is True
    assert result["checks"]["grand_total_verified"] is True
    assert len(result["discrepancies"]) == 0
    print(">>> [UNIT TEST 7 PASSED] Service charge + tax dining receipt verified cleanly (Score: 100.0%).")


def test_net_unit_price_discount_receipt():
    """Unit Test 8: Receipt where gross total is on header and net unit price is reported with discount."""
    receipt_data = {
        "vendor_name": "AEON CO. (M) BHD",
        "receipt_number": "2018051110133130177",
        "date": "2018-05-11",
        "currency": "MYR",
        "subtotal": 476.81,
        "tax": 26.99,
        "rounding_adjustment": -0.01,
        "total": 476.80,
        "total_quantity": 3,
        "items": [
            {
                "item_code": "000004921851",
                "description": "1000Z TP GIKEN",
                "quantity": 1,
                "unit_price": 89.21,
                "total": 93.90,
                "discount": 4.69
            },
            {
                "item_code": "000006227678",
                "description": "TEFAL COMFORT M",
                "quantity": 1,
                "unit_price": 141.55,
                "total": 169.00,
                "discount": 27.45
            },
            {
                "item_code": "000008612854",
                "description": "A1615545 TEFAL",
                "quantity": 1,
                "unit_price": 246.05,
                "total": 558.00,
                "discount": 311.95
            }
        ]
    }

    result = verify_receipt_math(receipt_data)
    assert result["is_valid"] is True, f"Expected valid AEON discount receipt, got: {result}"
    assert result["confidence_score"] == 100.0
    assert result["checks"]["total_quantity_verified"] is True
    assert result["checks"]["line_items_verified"] is True
    assert result["checks"]["subtotal_verified"] is True
    assert result["checks"]["grand_total_verified"] is True
    assert len(result["discrepancies"]) == 0
    print(">>> [UNIT TEST 8 PASSED] Net unit price with line discount verified cleanly (Score: 100.0%).")



# ============================================================
# INTEGRATION TESTS (EXTRACTION + VALIDATION PIPELINE)
# ============================================================
def test_single_receipt_extract_and_validate(receipt_path: Optional[Path] = None):
    """
    Test 5: Single Image Receipt Extraction and Deterministic Validation.
    """
    if receipt_path is None:
        receipt_path = get_default_sample_receipt()

    print("\n" + "=" * 80)
    print(f"TEST 5: SINGLE RECEIPT EXTRACTION -> VALIDATION PIPELINE")
    print(f"Target File: {receipt_path.name}")
    print("=" * 80)

    client = get_gemini_client()
    logger.info(f"[STAGE 1] Extracting structured data from {receipt_path.name}...")

    extracted_receipt: Optional[Receipt] = extract_single_receipt(client, receipt_path)

    assert extracted_receipt is not None, f"Extraction failed for {receipt_path.name}"
    assert isinstance(extracted_receipt, Receipt), (
        f"Expected instance of Receipt, got {type(extracted_receipt)}"
    )
    assert isinstance(extracted_receipt.items, list), "Extracted items must be a list"

    print("\n--- [STAGE 1 SUCCESS] Extracted Receipt Data ---")
    print(f"Vendor Name    : {extracted_receipt.vendor_name or 'N/A'}")
    print(f"Receipt Number : {extracted_receipt.receipt_number or 'N/A'}")
    print(f"Date           : {extracted_receipt.date or 'N/A'}")
    print(f"Currency       : {extracted_receipt.currency or 'N/A'}")
    print(f"Items Qty      : {len(extracted_receipt.items)}")
    print(f"Subtotal       : {extracted_receipt.subtotal}")
    print(f"Tax            : {extracted_receipt.tax}")
    print(f"Discount       : {extracted_receipt.discount_amount}")
    print(f"Total          : {extracted_receipt.total}")

    extracted_dict = extracted_receipt.model_dump(mode="json")

    logger.info("[STAGE 2] Running deterministic mathematical verification...")
    validation_report = verify_receipt_math(extracted_dict)

    assert isinstance(validation_report, dict), "Validation report must be a dictionary"
    assert "is_valid" in validation_report
    assert "confidence_score" in validation_report
    assert "checks" in validation_report
    assert "discrepancies" in validation_report
    assert "resolved_totals" in validation_report
    assert 0.0 <= validation_report["confidence_score"] <= 100.0

    print("\n--- [STAGE 2 SUCCESS] Receipt Validation Report ---")
    print(f"Is Mathematically Valid : {validation_report['is_valid']}")
    print(f"Confidence Score        : {validation_report['confidence_score']}%")
    print(f"Checks Performed        : {validation_report['checks']}")
    print(f"Discrepancies Found     : {validation_report['discrepancies'] if validation_report['discrepancies'] else 'None'}")
    print(f"Resolved Totals         : {validation_report['resolved_totals']}")

    print("\n>>> TEST 5 PASSED: Single Receipt Extraction -> Validation pipeline succeeded.")
    return extracted_dict, validation_report


def test_text_receipt_extract_and_validate():
    """
    Test 6: Plain Text (.txt) Receipt Extraction and Deterministic Validation.
    """
    print("\n" + "=" * 80)
    print("TEST 6: PLAIN TEXT (.txt) RECEIPT EXTRACTION -> VALIDATION PIPELINE")
    print("=" * 80)

    sample_receipt_text = """
RECEIPT
Store: Daily Fresh Mart
Receipt No: TXN-88412
Date: 2026-09-15

ITEMS:
1. Bananas (1kg)
   Qty: 2
   Price: 1.50
   Total: 3.00

2. Orange Juice 1L
   Qty: 1
   Price: 3.99
   Total: 3.99

3. Cheddar Cheese 200g
   Qty: 1
   Price: 4.50
   Total: 4.50

SUMMARY:
Subtotal: 11.49
Tax: 0.92
Rounding: -0.01
Total: 12.40

Payment: Cash
Change: 7.60
"""

    with tempfile.TemporaryDirectory() as temp_dir_str:
        txt_path = Path(temp_dir_str) / "sample_receipt.txt"
        txt_path.write_text(sample_receipt_text.strip(), encoding="utf-8")

        client = get_gemini_client()
        logger.info(f"Extracting plain text receipt from {txt_path.name}...")
        extracted_receipt = extract_single_receipt(client, txt_path)

        assert extracted_receipt is not None, "Failed to extract from plain text receipt"
        assert len(extracted_receipt.items) >= 2

        val_report = verify_receipt_math(extracted_receipt.model_dump(mode="json"))
        assert val_report["is_valid"] is True, f"Expected valid text receipt math, got: {val_report}"

        print(f"\n--- [TEXT RECEIPT SUCCESS] ---")
        print(f"Vendor Name      : {extracted_receipt.vendor_name}")
        print(f"Receipt Number   : {extracted_receipt.receipt_number}")
        print(f"Items Count      : {len(extracted_receipt.items)}")
        print(f"Confidence Score : {val_report['confidence_score']}%")
        print(f"Status           : {'VALID' if val_report['is_valid'] else 'FLAGGED'}")

    print("\n>>> TEST 6 PASSED: Plain text receipt extraction and validation succeeded.")


def test_integrated_single_receipt_helper():
    """
    Test 7: Tests the integrated helper process_and_validate_single_receipt()
    """
    sample_file = get_default_sample_receipt()

    print("\n" + "=" * 80)
    print("TEST 7: INTEGRATED SINGLE RECEIPT HELPER (process_and_validate_single_receipt)")
    print(f"Target File: {sample_file.name}")
    print("=" * 80)

    client = get_gemini_client()
    result = process_and_validate_single_receipt(client, sample_file)

    assert result is not None, "process_and_validate_single_receipt returned None"
    assert "file_name" in result
    assert "extracted_data" in result
    assert "validation_report" in result
    assert isinstance(result["validation_report"], dict)
    assert "confidence_score" in result["validation_report"]

    print("\nResult Keys:", list(result.keys()))
    print(f"File: {result['file_name']}")
    print(f"Receipt No: {result['validation_report'].get('receipt_number')}")
    print(f"Validation Score: {result['validation_report']['confidence_score']}%")
    print(f"Status: {'VALID' if result['validation_report']['is_valid'] else 'FLAGGED'}")

    print("\n>>> TEST 7 PASSED: Integrated single receipt helper function verified.")
    return result


def test_batch_extract_and_validate(
    start_index: int = 0,
    batch_size: int = 100,
    report_file: Optional[Path] = None,
):
    """
    Test 8: Batch Receipt Extraction and Validation Workflow with range slicing and JSON reporting.
    """
    all_files = sorted(
        [f for f in DATASET_RECEIPT_DIR.iterdir()
         if f.is_file() and f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".pdf"}]
    )
    sample_files = all_files[start_index : start_index + batch_size]
    assert len(sample_files) > 0, f"No sample receipt files available in range [{start_index}:{start_index + batch_size}]"

    print("\n" + "=" * 80)
    print(f"TEST 8: BATCH RECEIPT EXTRACTION -> VALIDATION PIPELINE")
    print(f"Sampling {len(sample_files)} receipt file(s) [{start_index + 1} to {start_index + len(sample_files)}] out of {len(all_files)} total")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        for f in sample_files:
            shutil.copy(f, temp_dir / f.name)

        logger.info(f"[STAGE 1] Running process_receipt_batch on {len(sample_files)} sample files...")
        extracted_batch = process_receipt_batch(temp_dir)

        assert len(extracted_batch) == len(sample_files), (
            f"Expected {len(sample_files)} extracted records, got {len(extracted_batch)}"
        )

        logger.info("[STAGE 2] Running verify_receipt_batch on extracted records...")
        audited_batch = verify_receipt_batch(extracted_batch)
        print_receipt_batch_validation_summary(audited_batch)

    # Save structured results to a report file
    if report_file is None:
        report_file = PROJECT_ROOT / "reports" / f"receipt_batch_set_{start_index + 1}_to_{start_index + len(sample_files)}.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(audited_batch, f, indent=2, default=str)
    print(f"\n[REPORT SAVED] Structured batch results saved to: {report_file}")

    print(">>> TEST 8 PASSED: Batch Receipt Extraction -> Validation workflow succeeded.")
    return audited_batch


# ============================================================
# MAIN TEST EXECUTION
# ============================================================
if __name__ == "__main__":
    print("\n" + "#" * 80)
    print("STARTING RECEIPT EXTRACTION & VALIDATION TEST SUITE")
    print("#" * 80)

    # CLI args: python test_receipt_pipeline.py [batch_size] [start_index]
    # Example: python test_receipt_pipeline.py 100 0   -> Set 1 (1 to 100)
    #          python test_receipt_pipeline.py 100 100 -> Set 2 (101 to 200)
    batch_size = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 100
    start_index = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 0

    try:
        # Unit Tests
        test_valid_receipt_model()
        test_math_error_receipt()
        test_missing_subtotal_reconciled()
        test_no_grand_total_receipt_passes_full_points()
        test_line_item_discount_deducted()
        test_tax_inclusive_receipt()
        test_service_charge_receipt()
        test_net_unit_price_discount_receipt()

        # Batch execution for the target slice
        test_batch_extract_and_validate(start_index=start_index, batch_size=batch_size)

        print("\n" + "#" * 80)
        print("ALL RECEIPT PIPELINE TESTS COMPLETED SUCCESSFULLY!")
        print("#" * 80 + "\n")

    except Exception as err:
        logger.critical(f"Receipt test suite encountered an error: {err}", exc_info=True)
        sys.exit(1)

