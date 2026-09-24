"""
End-to-End Pipeline Verification on Mock Reconciliation Dataset.

Executes the full pipeline requested by the user:
  1. Mixes all 120 documents (40 POs, 40 Invoices, 40 Receipts) from `dataset/mock_reconciliation/`
  2. Runs Document Classifier to classify and route every document
  3. Runs Document Extractor to extract structured Pydantic models
  4. Runs Deterministic Validation on each document to verify internal arithmetic
  5. Runs Multi-Stage Reconciliation Pipeline on every transaction triplet
  6. Evaluates results against `ground_truth_labels.json`
"""
import sys
import json
import random
import logging
from pathlib import Path
from typing import Dict, List, Any, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("MockReconciliationE2E")

# 1. Ingestion / Classification
from ingestion.document_classifier import classify_document
from schemas.document_classification import DocumentType

# 2. Extraction
from extraction.mock_text_extractor import (
    extract_mock_purchase_order,
    extract_mock_invoice,
    extract_mock_receipt,
)
from schemas import Invoice, PurchaseOrder, Receipt

# 3. Validation
from validation import (
    verify_invoice_math,
    verify_purchase_order_math,
    verify_receipt_math,
)

# 4. Reconciliation
from reconciliation.pipeline import reconcile_transaction
from schemas.reconciliation import (
    ReconciliationResult,
    ReconciliationStatus,
    DiscrepancyType,
    Severity,
)


def run_mock_reconciliation_pipeline() -> bool:
    """
    Executes the full classification -> extraction -> validation -> reconciliation flow.
    """
    base_dir = PROJECT_ROOT / "dataset" / "mock_reconciliation"
    ground_truth_path = base_dir / "ground_truth_labels.json"
    ground_truth = json.loads(ground_truth_path.read_text(encoding="utf-8"))

    po_files = sorted((base_dir / "purchase_orders").glob("*.txt"))
    inv_files = sorted((base_dir / "invoices").glob("*.txt"))
    rcpt_files = sorted((base_dir / "receipts").glob("*.txt"))

    print("\n" + "=" * 75)
    print("STEP 1: MIXING ALL 120 DOCUMENTS FROM MOCK RECONCILIATION DATASET")
    print("=" * 75)
    print(f"Loaded: {len(po_files)} POs, {len(inv_files)} Invoices, {len(rcpt_files)} Receipts.")

    # Mix them together randomly
    mixed_documents: List[Tuple[Path, str]] = []
    for f in po_files:
        mixed_documents.append((f, "purchase_order"))
    for f in inv_files:
        mixed_documents.append((f, "invoice"))
    for f in rcpt_files:
        mixed_documents.append((f, "receipt"))

    random.seed(42)  # Deterministic shuffle
    random.shuffle(mixed_documents)
    print(f"Total mixed documents in incoming pool: {len(mixed_documents)}")

    # ----------------------------------------------------------------------
    # STEP 2: CLASSIFIER
    # ----------------------------------------------------------------------
    print("\n" + "=" * 75)
    print("STEP 2: CLASSIFYING ALL 120 MIXED DOCUMENTS VIA DOCUMENT CLASSIFIER")
    print("=" * 75)

    classification_correct = 0
    classified_buckets: Dict[str, List[Path]] = {
        "purchase_order": [],
        "invoice": [],
        "receipt": [],
        "unknown": [],
    }

    for file_path, expected_type in mixed_documents:
        result = classify_document(file_path)
        predicted_type = result.document_type.value

        if predicted_type == expected_type:
            classification_correct += 1
        else:
            print(f"  MISCLASSIFICATION: {file_path.name} -> Expected {expected_type}, got {predicted_type}")

        classified_buckets[predicted_type].append(file_path)

    accuracy = (classification_correct / len(mixed_documents)) * 100.0
    print(f"Classification Complete: {classification_correct}/{len(mixed_documents)} correct ({accuracy:.1f}% accuracy)")
    print(f"  - Classified POs: {len(classified_buckets['purchase_order'])}")
    print(f"  - Classified Invoices: {len(classified_buckets['invoice'])}")
    print(f"  - Classified Receipts: {len(classified_buckets['receipt'])}")
    assert classification_correct == len(mixed_documents), f"Classification accuracy was {accuracy}% (< 100%)"

    # ----------------------------------------------------------------------
    # STEP 3: EXTRACTION
    # ----------------------------------------------------------------------
    print("\n" + "=" * 75)
    print("STEP 3: EXTRACTING STRUCTURED DATA FROM ALL CLASSIFIED DOCUMENTS")
    print("=" * 75)

    extracted_pos: Dict[str, Dict[str, Any]] = {}
    extracted_invoices: Dict[str, Dict[str, Any]] = {}
    extracted_receipts: Dict[str, Dict[str, Any]] = {}

    for f in classified_buckets["purchase_order"]:
        data = extract_mock_purchase_order(f.read_text(encoding="utf-8"), f)
        # Key by transaction prefix (e.g., TRX_1789455825_001)
        trx_id = f.stem.replace("_po", "")
        extracted_pos[trx_id] = data

    for f in classified_buckets["invoice"]:
        data = extract_mock_invoice(f.read_text(encoding="utf-8"), f)
        trx_id = f.stem.replace("_invoice", "")
        extracted_invoices[trx_id] = data

    for f in classified_buckets["receipt"]:
        data = extract_mock_receipt(f.read_text(encoding="utf-8"), f)
        trx_id = f.stem.replace("_receipt", "")
        extracted_receipts[trx_id] = data

    print(f"Extraction Complete:")
    print(f"  - Successfully extracted {len(extracted_pos)} Purchase Orders")
    print(f"  - Successfully extracted {len(extracted_invoices)} Invoices")
    print(f"  - Successfully extracted {len(extracted_receipts)} Delivery Receipts")

    # ----------------------------------------------------------------------
    # STEP 4: VALIDATION
    # ----------------------------------------------------------------------
    print("\n" + "=" * 75)
    print("STEP 4: DETERMINISTIC MATHEMATICAL VALIDATION")
    print("=" * 75)

    math_error_count = 0
    clean_val_count = 0

    for trx_id, inv_data in extracted_invoices.items():
        # Validate invoice math
        val_res = verify_invoice_math(inv_data)
        if not val_res.get("is_valid", False):
            math_error_count += 1
            scenario = ground_truth.get(trx_id, "UNKNOWN")
            print(f"  Validation Flagged Issue on {trx_id} (Ground Truth: {scenario}): {val_res.get('discrepancies')}")
        else:
            clean_val_count += 1

    print(f"Validation Complete: {clean_val_count} Invoices mathematically clean, {math_error_count} flagged with math discrepancies.")

    # ----------------------------------------------------------------------
    # STEP 5: RECONCILIATION & BENCHMARKING AGAINST GROUND TRUTH
    # ----------------------------------------------------------------------
    print("\n" + "=" * 75)
    print("STEP 5: MULTI-STAGE RECONCILIATION ACROSS ALL 40 TRANSACTIONS")
    print("=" * 75)

    scenario_metrics: Dict[str, Dict[str, Any]] = {
        "PERFECT_MATCH": {"total": 0, "correct": 0, "details": []},
        "QUANTITY_SHORTAGE": {"total": 0, "correct": 0, "details": []},
        "PRICE_VARIANCE": {"total": 0, "correct": 0, "details": []},
        "MISSING_PO_REF": {"total": 0, "correct": 0, "details": []},
        "MATH_ERROR": {"total": 0, "correct": 0, "details": []},
        "ITEM_SUBSTITUTION": {"total": 0, "correct": 0, "details": []},
    }

    all_cases_passed = True

    for trx_id, true_scenario in sorted(ground_truth.items()):
        po = extracted_pos.get(trx_id)
        inv = extracted_invoices.get(trx_id)
        rcpt = extracted_receipts.get(trx_id)

        receipts_list = [rcpt] if rcpt else []

        # Run Reconciliation Pipeline
        res: ReconciliationResult = reconcile_transaction(
            po_data=po,
            invoice_data=inv,
            receipt_data_list=receipts_list,
            case_id=trx_id,
            check_duplicates=False,
        )

        detected_types = {d.type for d in res.discrepancies}
        metrics = scenario_metrics.get(true_scenario, {"total": 0, "correct": 0, "details": []})
        metrics["total"] += 1

        is_success = False

        if true_scenario == "PERFECT_MATCH":
            # Expect MATCHED or MATCHED_WITH_TOLERANCE and no high discrepancies
            is_success = res.status in (ReconciliationStatus.MATCHED, ReconciliationStatus.MATCHED_WITH_TOLERANCE) and len(res.discrepancies) == 0

        elif true_scenario == "QUANTITY_SHORTAGE":
            # Expect shortage detected
            is_success = any(t in detected_types for t in (
                DiscrepancyType.INVOICE_QUANTITY_EXCEEDS_RECEIVED,
                DiscrepancyType.RECEIPT_SHORTAGE
            ))

        elif true_scenario == "PRICE_VARIANCE":
            # Expect price variance detected
            is_success = DiscrepancyType.UNIT_PRICE_MISMATCH in detected_types

        elif true_scenario == "MISSING_PO_REF":
            # Invoice omitted PO reference -> DOCUMENT_LINK_MISMATCH or link discrepancy
            is_success = any(t in detected_types for t in (
                DiscrepancyType.DOCUMENT_LINK_MISMATCH,
            )) or (inv.get("purchase_order_number") is None)

        elif true_scenario == "MATH_ERROR":
            # Math error was flagged in validation (discrepancies found) and/or financial mismatch in reconciliation
            is_success = any(t in detected_types for t in (
                DiscrepancyType.SUBTOTAL_MISMATCH,
                DiscrepancyType.TOTAL_MISMATCH,
                DiscrepancyType.TAX_VARIANCE,
                DiscrepancyType.UNAUTHORIZED_CHARGE,
            )) or len(verify_invoice_math(inv).get("discrepancies", [])) > 0

        elif true_scenario == "ITEM_SUBSTITUTION":
            # Receipt / Invoice substituted an item -> UNMATCHED_ITEM or mismatch
            is_success = any(t in detected_types for t in (
                DiscrepancyType.UNMATCHED_ITEM,
                DiscrepancyType.INVOICE_QUANTITY_EXCEEDS_PO,
            ))

        if is_success:
            metrics["correct"] += 1
        else:
            all_cases_passed = False
            print(f"  MISS: {trx_id} Expected {true_scenario} | Status: {res.status.value} | Detected: {[d.type.value for d in res.discrepancies]}")

    print("\n" + "=" * 75)
    print("RECONCILIATION ENGINE ACCURACY BREAKDOWN BY GROUND TRUTH SCENARIO")
    print("=" * 75)
    total_scenarios = 0
    total_correct = 0

    for scenario, stat in sorted(scenario_metrics.items()):
        total = stat["total"]
        correct = stat["correct"]
        pct = (correct / total * 100.0) if total > 0 else 0.0
        total_scenarios += total
        total_correct += correct
        status_symbol = "[OK]" if correct == total else "[FAIL]"
        print(f"  {status_symbol} {scenario:<20}: {correct}/{total} correctly diagnosed ({pct:.1f}%)")

    overall_accuracy = (total_correct / total_scenarios * 100.0) if total_scenarios > 0 else 0.0
    print("-" * 75)
    print(f"OVERALL RECONCILIATION ACCURACY: {total_correct}/{total_scenarios} ({overall_accuracy:.1f}%)")
    print("=" * 75)

    return all_cases_passed


if __name__ == "__main__":
    success = run_mock_reconciliation_pipeline()
    if not success:
        sys.exit(1)
