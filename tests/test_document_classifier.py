"""
Comprehensive Test Suite for Universal Document Classifier.

Verifies:
1. Synthetic text heuristics (Invoice, PO, Delivery Receipt)
2. Real-world dataset files (PDF purchase orders, TXT invoices, TXT POs, TXT delivery receipts, JPG receipts)
3. Mixed-folder ingestion simulation with auto-organization (copy/move)
4. Speed and accuracy benchmarks
"""
import os
import sys
import shutil
import tempfile
import logging
from pathlib import Path

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

from schemas.document_classification import DocumentType, PipelineTarget
from ingestion.document_classifier import (
    classify_document,
    classify_text_heuristics,
    classify_and_organize_directory,
    extract_text_if_available,
    get_gemini_client,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("TestDocumentClassifier")


def test_synthetic_invoice_text():
    """Unit Test 1: Synthetic invoice text classifies cleanly as INVOICE."""
    text = """
    ================================================================================
    COMMERCIAL INVOICE
    ================================================================================
    Invoice Number: INV-99021
    Invoice Date: 2026-03-01
    Payment Due Date: 2026-03-31
    Payment Terms: Net 30
    PO Reference: PO-88319

    VENDOR: Acro Dynamics Corp
    BILL TO: MegaCorp Global
    Remit To: Bank of America, Acct: 12345678, Routing: 99887766

    SKU / ITEM       QTY    UNIT PRICE     TOTAL
    AC-100            2        $500.00  $1,000.00
    SUBTOTAL: $1,000.00
    TAX:         $80.00
    GRAND TOTAL: $1,080.00
    """
    path = Path("fake_invoice.txt")
    res = classify_text_heuristics(text, path)
    assert res is not None, "Failed to classify invoice text"
    assert res.document_type == DocumentType.INVOICE
    assert res.suggested_pipeline == PipelineTarget.INVOICE_PIPELINE
    assert res.confidence >= 0.90
    print(">>> [UNIT TEST 1 PASSED] Synthetic invoice text classified as INVOICE.")


def test_synthetic_po_text():
    """Unit Test 2: Synthetic PO text classifies cleanly as PURCHASE_ORDER."""
    text = """
    ================================================================================
    PURCHASE ORDER
    ================================================================================
    PO Number: PO-44820
    PO Date: 2026-02-15
    Payment Terms: Net 30
    FOB Point: Origin

    VENDOR: Global Logistics Supply
    BILL TO: MegaCorp Global
    SHIP TO: Warehouse Dock 4

    SKU / ITEM       QTY    UNIT PRICE     TOTAL
    GL-882            10        $25.00    $250.00
    SUBTOTAL: $250.00
    GRAND TOTAL: $250.00
    Authorized Signature: _______________________ (Purchasing Dept)
    Terms & Conditions: Reference PO-44820 on all shipping docs.
    """
    path = Path("fake_po.txt")
    res = classify_text_heuristics(text, path)
    assert res is not None, "Failed to classify PO text"
    assert res.document_type == DocumentType.PURCHASE_ORDER
    assert res.suggested_pipeline == PipelineTarget.PO_PIPELINE
    assert res.confidence >= 0.90
    print(">>> [UNIT TEST 2 PASSED] Synthetic PO text classified as PURCHASE_ORDER.")


def test_synthetic_delivery_receipt_text():
    """Unit Test 3: Synthetic delivery receipt text classifies cleanly as RECEIPT."""
    text = """
    ================================================================================
    DELIVERY RECEIPT
    ================================================================================
    Receipt Number: DR-11029
    Delivery Date: 2026-02-20
    PO Reference: PO-44820

    VENDOR: Global Logistics Supply
    DELIVERED TO: Warehouse Dock 4
    Carrier: DHL Express (Tracking #: 987654321)

    SKU / ITEM       QTY ORDERED   QTY DELIVERED
    GL-882                    10              10
    Status: Delivered in good condition
    Received By: John Doe (Signed)
    Time of Delivery: 10:15 AM
    """
    path = Path("fake_receipt.txt")
    res = classify_text_heuristics(text, path)
    assert res is not None, "Failed to classify delivery receipt text"
    assert res.document_type == DocumentType.RECEIPT
    assert res.suggested_pipeline == PipelineTarget.RECEIPT_PIPELINE
    assert res.confidence >= 0.90
    print(">>> [UNIT TEST 3 PASSED] Synthetic delivery receipt classified as RECEIPT.")


def test_real_po_pdf_classification():
    """Unit Test 4: Real purchase order PDF classifies as PURCHASE_ORDER via Tier 1 local text."""
    po_file = PROJECT_ROOT / "dataset" / "standalone" / "purchase_orders" / "purchase_orders_10248.pdf"
    assert po_file.exists(), f"File not found: {po_file}"

    res = classify_document(po_file)
    assert res.document_type == DocumentType.PURCHASE_ORDER
    assert res.tier_used == "local_text"
    assert res.suggested_pipeline == PipelineTarget.PO_PIPELINE
    assert res.confidence >= 0.90
    print(f">>> [UNIT TEST 4 PASSED] Real PO PDF {po_file.name} classified as PURCHASE_ORDER ({res.confidence * 100:.1f}%).")


def test_real_standalone_invoice_classification():
    """Unit Test 5: Real standalone invoice text classifies as INVOICE via Tier 1."""
    inv_file = PROJECT_ROOT / "dataset" / "standalone" / "invoices" / "TRX_1789455825_001_invoice.txt"
    assert inv_file.exists(), f"File not found: {inv_file}"

    res = classify_document(inv_file)
    assert res.document_type == DocumentType.INVOICE
    assert res.tier_used == "local_text"
    assert res.suggested_pipeline == PipelineTarget.INVOICE_PIPELINE
    assert res.confidence >= 0.90
    print(f">>> [UNIT TEST 5 PASSED] Real Invoice {inv_file.name} classified as INVOICE ({res.confidence * 100:.1f}%).")


def test_real_mock_po_classification():
    """Unit Test 6: Real mock PO text classifies as PURCHASE_ORDER via Tier 1."""
    mpo_file = PROJECT_ROOT / "dataset" / "mock_reconciliation" / "purchase_orders" / "TRX_1789455825_001_po.txt"
    assert mpo_file.exists(), f"File not found: {mpo_file}"

    res = classify_document(mpo_file)
    assert res.document_type == DocumentType.PURCHASE_ORDER
    assert res.tier_used == "local_text"
    assert res.suggested_pipeline == PipelineTarget.PO_PIPELINE
    assert res.confidence >= 0.90
    print(f">>> [UNIT TEST 6 PASSED] Real Mock PO {mpo_file.name} classified as PURCHASE_ORDER ({res.confidence * 100:.1f}%).")


def test_real_mock_receipt_classification():
    """Unit Test 7: Real mock delivery receipt classifies as RECEIPT via Tier 1."""
    mrc_file = PROJECT_ROOT / "dataset" / "mock_reconciliation" / "receipts" / "TRX_1789455825_001_receipt.txt"
    assert mrc_file.exists(), f"File not found: {mrc_file}"

    res = classify_document(mrc_file)
    assert res.document_type == DocumentType.RECEIPT
    assert res.tier_used == "local_text"
    assert res.suggested_pipeline == PipelineTarget.RECEIPT_PIPELINE
    assert res.confidence >= 0.90
    print(f">>> [UNIT TEST 7 PASSED] Real Mock Receipt {mrc_file.name} classified as RECEIPT ({res.confidence * 100:.1f}%).")


def test_real_retail_receipt_image_classification():
    """Unit Test 8: Real retail receipt image classifies as RECEIPT via Tier 2 Multimodal Vision."""
    client = get_gemini_client()
    if not client:
        print(">>> [UNIT TEST 8 SKIPPED] Gemini API key not set, skipping vision test.")
        return

    receipt_file = PROJECT_ROOT / "dataset" / "standalone" / "receipts" / "receipt_0001.jpg"
    assert receipt_file.exists(), f"File not found: {receipt_file}"

    res = classify_document(receipt_file, client=client)
    assert res.document_type == DocumentType.RECEIPT
    assert res.tier_used == "multimodal_vision"
    assert res.suggested_pipeline == PipelineTarget.RECEIPT_PIPELINE
    assert res.confidence >= 0.90
    print(f">>> [UNIT TEST 8 PASSED] Real Retail Receipt {receipt_file.name} classified as RECEIPT ({res.confidence * 100:.1f}%).")


def test_mixed_folder_simulation():
    """
    Integration Test 9: Mixed Folder Dump Simulation.
    Creates a temporary mixed directory containing invoices, POs, and receipts of various formats.
    Runs classify_and_organize_directory(mode='copy') and verifies:
    - 100% classification accuracy
    - Physical organization into /invoices, /purchase_orders, and /receipts
    - JSON audit report creation
    """
    print("\n" + "=" * 80)
    print("INTEGRATION TEST: MIXED FOLDER INGESTION & AUTO-ORGANIZATION")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as temp_in_str, tempfile.TemporaryDirectory() as temp_out_str:
        temp_in = Path(temp_in_str)
        temp_out = Path(temp_out_str)

        # 1. Populate mixed folder with various file types
        dataset_root = PROJECT_ROOT / "dataset"
        ground_truth: dict = {}

        # 5 PO PDFs
        for f in sorted((dataset_root / "standalone" / "purchase_orders").glob("*.pdf"))[:5]:
            shutil.copy2(f, temp_in / f.name)
            ground_truth[f.name] = DocumentType.PURCHASE_ORDER

        # 5 Invoices TXT
        for f in sorted((dataset_root / "standalone" / "invoices").glob("*.txt"))[:5]:
            shutil.copy2(f, temp_in / f.name)
            ground_truth[f.name] = DocumentType.INVOICE

        # 5 Mock POs TXT
        for f in sorted((dataset_root / "mock_reconciliation" / "purchase_orders").glob("*.txt"))[:5]:
            shutil.copy2(f, temp_in / f.name)
            ground_truth[f.name] = DocumentType.PURCHASE_ORDER

        # 5 Mock Delivery Receipts TXT
        for f in sorted((dataset_root / "mock_reconciliation" / "receipts").glob("*.txt"))[:5]:
            shutil.copy2(f, temp_in / f.name)
            ground_truth[f.name] = DocumentType.RECEIPT

        # 3 Standalone Retail Receipts JPG
        for f in sorted((dataset_root / "standalone" / "receipts").glob("*.jpg"))[:3]:
            shutil.copy2(f, temp_in / f.name)
            ground_truth[f.name] = DocumentType.RECEIPT

        print(f"Constructed mixed input folder with {len(ground_truth)} total files across all formats.")

        # 2. Run classify_and_organize_directory
        client = get_gemini_client()
        report = classify_and_organize_directory(
            input_dir=temp_in,
            output_dir=temp_out,
            mode="copy",
            client=client,
        )

        assert report.total_files == len(ground_truth)

        # 3. Verify accuracy
        correct = 0
        for res in report.results:
            expected = ground_truth[res.file_name]
            assert res.document_type == expected, (
                f"Mismatch for {res.file_name}: expected {expected}, got {res.document_type}"
            )
            correct += 1

        accuracy = (correct / len(ground_truth)) * 100.0
        print(f"Classification Accuracy: {correct}/{len(ground_truth)} ({accuracy:.1f}%)")
        assert accuracy == 100.0, f"Expected 100% accuracy, got {accuracy}%"

        # 4. Verify physical directory routing
        invoices_routed = list((temp_out / "invoices").iterdir())
        pos_routed = list((temp_out / "purchase_orders").iterdir())
        receipts_routed = list((temp_out / "receipts").iterdir())

        assert len(invoices_routed) == 5, f"Expected 5 invoices, got {len(invoices_routed)}"
        assert len(pos_routed) == 10, f"Expected 10 POs (5 PDF + 5 TXT), got {len(pos_routed)}"
        assert len(receipts_routed) == 8, f"Expected 8 receipts (5 TXT + 3 JPG), got {len(receipts_routed)}"
        assert (temp_out / "classification_report.json").exists()

        print(f"Organized Subdirectories:")
        print(f"  - invoices/       : {len(invoices_routed)} files")
        print(f"  - purchase_orders/: {len(pos_routed)} files")
        print(f"  - receipts/       : {len(receipts_routed)} files")
        print(f"  - report saved    : classification_report.json")

    print("\n>>> INTEGRATION TEST PASSED: Mixed folder classified and organized with 100.0% accuracy!")


def benchmark_all_text_and_pdf_documents():
    """
    Benchmark Test: Runs local classifier across all 600 text & PDF files in dataset
    (480 PO PDFs, 40 Standalone Invoices, 40 Mock POs, 40 Mock Receipts).
    Verifies 100% accuracy and millisecond latency.
    """
    print("\n" + "=" * 80)
    print("DATASET BENCHMARK: 600 LOCAL TEXT & PDF DOCUMENTS")
    print("=" * 80)

    dataset_root = PROJECT_ROOT / "dataset"
    test_targets = [
        ("480 Standalone PO PDFs", dataset_root / "standalone" / "purchase_orders", "*.pdf", DocumentType.PURCHASE_ORDER),
        ("40 Standalone Invoices", dataset_root / "standalone" / "invoices", "*.txt", DocumentType.INVOICE),
        ("40 Mock POs", dataset_root / "mock_reconciliation" / "purchase_orders", "*.txt", DocumentType.PURCHASE_ORDER),
        ("40 Mock Receipts", dataset_root / "mock_reconciliation" / "receipts", "*.txt", DocumentType.RECEIPT),
    ]

    grand_total = 0
    grand_correct = 0

    for label, folder, pattern, expected in test_targets:
        files = list(folder.glob(pattern))
        correct = 0
        for f in files:
            res = classify_document(f)
            if res.document_type == expected:
                correct += 1
            else:
                logger.warning(f"Classification failure on {f.name}: expected {expected}, got {res.document_type}")

        grand_total += len(files)
        grand_correct += correct
        pct = (correct / len(files)) * 100.0
        print(f"  {label:<28}: {correct:3d}/{len(files):3d} correct ({pct:5.1f}%)")

    overall_pct = (grand_correct / grand_total) * 100.0
    print("-" * 80)
    print(f"TOTAL BENCHMARK SCORE: {grand_correct}/{grand_total} correct ({overall_pct:.2f}%)")
    print("=" * 80 + "\n")
    assert grand_correct == grand_total, f"Benchmark failed: {grand_correct}/{grand_total}"


if __name__ == "__main__":
    print("\n" + "#" * 80)
    print("STARTING DOCUMENT CLASSIFIER TEST SUITE")
    print("#" * 80 + "\n")

    # Unit Tests
    test_synthetic_invoice_text()
    test_synthetic_po_text()
    test_synthetic_delivery_receipt_text()
    test_real_po_pdf_classification()
    test_real_standalone_invoice_classification()
    test_real_mock_po_classification()
    test_real_mock_receipt_classification()
    test_real_retail_receipt_image_classification()

    # Integration Test
    test_mixed_folder_simulation()

    # Dataset Benchmark
    benchmark_all_text_and_pdf_documents()

    print("#" * 80)
    print("ALL DOCUMENT CLASSIFIER TESTS COMPLETED SUCCESSFULLY!")
    print("#" * 80 + "\n")

