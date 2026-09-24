import os
import sys
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
DATASET_PO_DIR = PROJECT_ROOT / "dataset" / "standalone" / "purchase_orders"

# Ensure src is in sys.path
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Load .env file from project root
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

from google import genai
from schemas import PurchaseOrder, PurchaseOrderItem
from extraction import (
    extract_single_purchase_order,
    process_purchase_order_batch,
    process_and_validate_single_purchase_order,
)
from validation import (
    verify_purchase_order_math,
    verify_purchase_order_batch,
    print_po_batch_validation_summary,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("TestPOPipeline")


def get_gemini_client() -> genai.Client:
    """Initializes and returns the Gemini API client from environment variables."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY environment variable is not set. "
            "Please configure it in the .env file at the project root."
        )
    return genai.Client(api_key=api_key)


def get_default_sample_po() -> Path:
    """Finds the first available purchase order PDF in the dataset directory."""
    if not DATASET_PO_DIR.exists():
        raise FileNotFoundError(f"Dataset directory not found: {DATASET_PO_DIR}")

    sample_files = sorted(
        [f for f in DATASET_PO_DIR.iterdir() if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".pdf"}]
    )
    if not sample_files:
        raise FileNotFoundError(f"No PO images or PDFs found in: {DATASET_PO_DIR}")

    return sample_files[0]


# ============================================================
# UNIT TESTS (DETERMINISTIC VERIFICATION ENGINE)
# ============================================================
def test_valid_po_model():
    """Unit Test 1: Pydantic PurchaseOrder model with accurate math passes verification at 100%."""
    po = PurchaseOrder(
        purchase_order_number="PO-2026-8801",
        vendor_name="Global Steel & Fasteners Inc.",
        buyer_name="Northwind Construction LLC",
        items=[
            PurchaseOrderItem(
                product_code="BOLT-M12",
                description="M12 Galvanized Hex Bolts 100pk",
                quantity=Decimal("10"),
                unit_price=Decimal("15.50"),
                discount=Decimal("5.00"),
                tax=Decimal("0.00"),
                line_total=Decimal("150.00"),
            ),
            PurchaseOrderItem(
                product_code="WASH-M12",
                description="M12 Flat Washers 100pk",
                quantity=Decimal("5"),
                unit_price=Decimal("4.20"),
                discount=Decimal("0.00"),
                tax=Decimal("2.00"),
                line_total=Decimal("23.00"),
            ),
        ],
        subtotal=Decimal("173.00"),
        discount=Decimal("10.00"),
        tax=Decimal("14.94"),
        shipping=Decimal("15.00"),
        rounding_adjustment=Decimal("-0.04"),
        total=Decimal("192.90"),
    )

    result = verify_purchase_order_math(po)
    assert result["is_valid"] is True, f"Expected valid PO, got: {result}"
    assert result["confidence_score"] == 100.0
    assert result["checks"]["line_items_verified"] is True
    assert result["checks"]["subtotal_verified"] is True
    assert result["checks"]["grand_total_verified"] is True
    print(">>> [UNIT TEST 1 PASSED] Valid PurchaseOrder verified cleanly (Score: 100.0%).")


def test_math_error_po():
    """Unit Test 2: Deliberate math errors cause verification failure and report discrepancies."""
    bad_po = {
        "purchase_order_number": "PO-ERR-999",
        "items": [
            {
                "description": "Defective Widget",
                "quantity": 10,
                "unit_price": 50.00,
                "line_total": 600.00,  # Math error: 10 * 50 = 500
            }
        ],
        "subtotal": 600.00,
        "total": 500.00,  # Grand total error: subtotal 600 != total 500
    }

    result = verify_purchase_order_math(bad_po)
    assert result["is_valid"] is False
    assert len(result["discrepancies"]) > 0
    print(f">>> [UNIT TEST 2 PASSED] Math error PO correctly flagged (Score: {result['confidence_score']}%).")
    print(f"    Discrepancies: {result['discrepancies']}")


def test_missing_subtotal_reconciled():
    """Unit Test 3: Subtotal omitted passes 100% when line item sum reconciles with grand total."""
    po_data = {
        "purchase_order_number": "PO-NO-SUBTOTAL-01",
        "items": [
            {"description": "Industrial Sensor", "quantity": 2, "unit_price": 50.00, "line_total": 100.00},
            {"description": "Mounting Bracket", "quantity": 4, "unit_price": 10.00, "line_total": 40.00},
        ],
        "subtotal": None,
        "shipping": 10.00,
        "tax": 5.00,
        "total": 155.00,  # 140 + 10 + 5 = 155.00
    }

    result = verify_purchase_order_math(po_data)
    assert result["is_valid"] is True
    assert result["confidence_score"] == 100.0
    assert result["checks"]["subtotal_verified"] is True
    assert result["checks"]["grand_total_verified"] is True
    assert len(result["discrepancies"]) == 0
    print(">>> [UNIT TEST 3 PASSED] Omitted subtotal reconciled via grand total (Score: 100.0%).")


def test_no_grand_total_po_passes_full_points():
    """Unit Test 4: PO with no grand total or subtotal awards full points without flagging."""
    po_data = {
        "purchase_order_number": "PO-NO-TOTALS-88",
        "items": [
            {"description": "Industrial Bearing", "quantity": 10, "unit_price": 25.00, "line_total": 250.00},
            {"description": "O-Ring Seal Pack", "quantity": 5, "unit_price": 4.00, "line_total": 20.00},
        ],
        "subtotal": None,
        "total": None,
    }

    result = verify_purchase_order_math(po_data)
    assert result["is_valid"] is True, f"Expected valid PO without totals, got: {result}"
    assert result["confidence_score"] == 100.0
    assert result["checks"]["line_items_verified"] is True
    assert result["checks"]["subtotal_verified"] is True
    assert result["checks"]["grand_total_verified"] is True
    assert len(result["discrepancies"]) == 0
    print(">>> [UNIT TEST 4 PASSED] PO with no grand total awarded full points without flagging.")


# ============================================================
# INTEGRATION TESTS (EXTRACTION + VALIDATION PIPELINE)
# ============================================================
def test_single_purchase_order_extract_and_validate(po_path: Optional[Path] = None):
    """
    Test 4: Single PDF Purchase Order Extraction and Deterministic Validation.
    """
    if po_path is None:
        po_path = get_default_sample_po()

    print("\n" + "=" * 80)
    print(f"TEST 4: SINGLE PO EXTRACTION -> VALIDATION PIPELINE")
    print(f"Target File: {po_path.name}")
    print("=" * 80)

    client = get_gemini_client()
    logger.info(f"[STAGE 1] Extracting structured data from {po_path.name}...")

    extracted_po: Optional[PurchaseOrder] = extract_single_purchase_order(client, po_path)

    assert extracted_po is not None, f"Extraction failed for {po_path.name}"
    assert isinstance(extracted_po, PurchaseOrder), (
        f"Expected instance of PurchaseOrder, got {type(extracted_po)}"
    )
    assert extracted_po.purchase_order_number is not None, "Extracted PO missing purchase_order_number"
    assert isinstance(extracted_po.items, list), "Extracted items must be a list"

    print("\n--- [STAGE 1 SUCCESS] Extracted Purchase Order Data ---")
    print(f"PO Number   : {extracted_po.purchase_order_number}")
    print(f"Vendor Name : {extracted_po.vendor_name or 'N/A'}")
    print(f"Buyer Name  : {extracted_po.buyer_name or 'N/A'}")
    print(f"Items Qty   : {len(extracted_po.items)}")
    print(f"Subtotal    : {extracted_po.subtotal}")
    print(f"Tax         : {extracted_po.tax}")
    print(f"Discount    : {extracted_po.discount}")
    print(f"Shipping    : {extracted_po.shipping}")
    print(f"Total       : {extracted_po.total}")

    extracted_dict = extracted_po.model_dump(mode="json")

    logger.info("[STAGE 2] Running deterministic mathematical verification...")
    validation_report = verify_purchase_order_math(extracted_dict)

    assert isinstance(validation_report, dict), "Validation report must be a dictionary"
    assert "is_valid" in validation_report
    assert "confidence_score" in validation_report
    assert "checks" in validation_report
    assert "discrepancies" in validation_report
    assert "resolved_totals" in validation_report
    assert 0.0 <= validation_report["confidence_score"] <= 100.0

    print("\n--- [STAGE 2 SUCCESS] Purchase Order Validation Report ---")
    print(f"Is Mathematically Valid : {validation_report['is_valid']}")
    print(f"Confidence Score        : {validation_report['confidence_score']}%")
    print(f"Checks Performed        : {validation_report['checks']}")
    print(f"Discrepancies Found     : {validation_report['discrepancies'] if validation_report['discrepancies'] else 'None'}")
    print(f"Resolved Totals         : {validation_report['resolved_totals']}")

    print("\n>>> TEST 4 PASSED: Single PO Extraction -> Validation pipeline succeeded.")
    return extracted_dict, validation_report


def test_text_purchase_order_extract_and_validate():
    """
    Test 5: Plain Text (.txt) Purchase Order Extraction and Deterministic Validation.
    """
    print("\n" + "=" * 80)
    print("TEST 5: PLAIN TEXT (.txt) PO EXTRACTION -> VALIDATION PIPELINE")
    print("=" * 80)

    sample_po_text = """
PURCHASE ORDER
PO Number: PO-77291
Date: 2026-03-15
Delivery Date: 2026-04-01

VENDOR:
Apex Industrial Hardware
100 Industrial Parkway, Detroit, MI 48201

BUYER:
Metro Heavy Machinery Corp
500 Construction Way, Chicago, IL 60601

LINE ITEMS:
1. Product Code: BEARING-01
   Description: Heavy Duty Roller Bearing
   Quantity: 10
   Unit: pcs
   Unit Price: 45.00
   Discount: 0.00
   Tax: 0.00
   Line Total: 450.00

2. Product Code: SEAL-99
   Description: High Temp O-Ring Seal Pack
   Quantity: 5
   Unit: pack
   Unit Price: 12.00
   Discount: 0.00
   Tax: 0.00
   Line Total: 60.00

SUMMARY:
Subtotal: 510.00
Discount: 20.00
Tax: 25.50
Shipping: 15.00
Rounding Adjustment: 0.00
Total: 530.50

Payment Terms: Net 30
Delivery Terms: FOB Destination
"""

    with tempfile.TemporaryDirectory() as temp_dir_str:
        txt_path = Path(temp_dir_str) / "sample_purchase_order.txt"
        txt_path.write_text(sample_po_text.strip(), encoding="utf-8")

        client = get_gemini_client()
        logger.info(f"Extracting plain text PO from {txt_path.name}...")
        extracted_po = extract_single_purchase_order(client, txt_path)

        assert extracted_po is not None, "Failed to extract from plain text purchase order"
        assert extracted_po.purchase_order_number == "PO-77291"
        assert len(extracted_po.items) == 2

        val_report = verify_purchase_order_math(extracted_po.model_dump(mode="json"))
        assert val_report["is_valid"] is True, f"Expected valid text PO math, got: {val_report}"
        assert val_report["confidence_score"] == 100.0

        print(f"\n--- [TEXT PO SUCCESS] ---")
        print(f"PO Number        : {extracted_po.purchase_order_number}")
        print(f"Vendor Name      : {extracted_po.vendor_name}")
        print(f"Buyer Name       : {extracted_po.buyer_name}")
        print(f"Confidence Score : {val_report['confidence_score']}%")
        print(f"Status           : {'VALID' if val_report['is_valid'] else 'FLAGGED'}")

    print("\n>>> TEST 5 PASSED: Plain text PO extraction and validation succeeded.")


def test_integrated_single_po_helper():
    """
    Test 6: Tests the integrated helper process_and_validate_single_purchase_order()
    """
    sample_file = get_default_sample_po()

    print("\n" + "=" * 80)
    print("TEST 6: INTEGRATED SINGLE PO HELPER (process_and_validate_single_purchase_order)")
    print(f"Target File: {sample_file.name}")
    print("=" * 80)

    client = get_gemini_client()
    result = process_and_validate_single_purchase_order(client, sample_file)

    assert result is not None, "process_and_validate_single_purchase_order returned None"
    assert "file_name" in result
    assert "extracted_data" in result
    assert "validation_report" in result
    assert isinstance(result["validation_report"], dict)
    assert "confidence_score" in result["validation_report"]

    print("\nResult Keys:", list(result.keys()))
    print(f"File: {result['file_name']}")
    print(f"PO No: {result['validation_report'].get('purchase_order_number')}")
    print(f"Validation Score: {result['validation_report']['confidence_score']}%")
    print(f"Status: {'VALID' if result['validation_report']['is_valid'] else 'FLAGGED'}")

    print("\n>>> TEST 6 PASSED: Integrated single PO helper function verified.")
    return result


def test_batch_extract_and_validate(max_sample_files: int = 2):
    """
    Test 7: Batch PO Extraction and Validation Workflow.
    """
    print("\n" + "=" * 80)
    print(f"TEST 7: BATCH PO EXTRACTION -> VALIDATION PIPELINE")
    print(f"Sampling {max_sample_files} PO file(s) for controlled batch execution")
    print("=" * 80)

    all_files = sorted(
        [f for f in DATASET_PO_DIR.iterdir() if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".pdf"}]
    )
    sample_files = all_files[:max_sample_files]
    assert len(sample_files) > 0, "No sample PO files available for batch testing"

    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        for f in sample_files:
            shutil.copy(f, temp_dir / f.name)

        logger.info(f"[STAGE 1] Running process_purchase_order_batch on {len(sample_files)} sample files...")
        extracted_batch = process_purchase_order_batch(temp_dir)

        assert len(extracted_batch) == len(sample_files), (
            f"Expected {len(sample_files)} extracted records, got {len(extracted_batch)}"
        )

        logger.info("[STAGE 2] Running verify_purchase_order_batch on extracted records...")
        audited_batch = verify_purchase_order_batch(extracted_batch)
        print_po_batch_validation_summary(audited_batch)

    print(">>> TEST 7 PASSED: Batch PO Extraction -> Validation workflow succeeded.")
    return audited_batch


# ============================================================
# MAIN TEST EXECUTION
# ============================================================
if __name__ == "__main__":
    print("\n" + "#" * 80)
    print("STARTING PURCHASE ORDER EXTRACTION & VALIDATION TEST SUITE")
    print("#" * 80)

    # Allow custom batch size via CLI argument (default to 100 as originally configured)
    batch_count = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 100

    try:
        # Unit Tests
        test_valid_po_model()
        test_math_error_po()
        test_missing_subtotal_reconciled()
        test_no_grand_total_po_passes_full_points()

        # Integration Tests with Gemini Model
        test_single_purchase_order_extract_and_validate()
        test_text_purchase_order_extract_and_validate()
        test_integrated_single_po_helper()
        test_batch_extract_and_validate(max_sample_files=batch_count)

        print("\n" + "#" * 80)
        print("ALL PURCHASE ORDER PIPELINE TESTS COMPLETED SUCCESSFULLY!")
        print("#" * 80 + "\n")

    except Exception as err:
        logger.critical(f"PO test suite encountered an error: {err}", exc_info=True)
        sys.exit(1)
