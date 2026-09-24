"""
Test Suite for Master Orchestration Pipeline (`src/pipeline/orchestrator.py`).

Tests the assembly line coordination:
  1. Single transaction clean match (Reconciliation -> MATCHED -> Auto-Approve)
  2. Single transaction discrepancy (Reconciliation -> DISCREPANCY -> Agent Investigation -> Findings -> Review Queue)
  3. Raw document ingestion across mixed file inputs (Classifier -> Extractor -> Validator -> Reconciler -> Agent)
  4. Batch directory processing and reporting
"""
import sys
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pipeline.orchestrator import (
    MasterOrchestrator,
    TransactionResult,
    OrchestrationReport,
)
from agent.db import InvestigationDatabase
from agent.review_queue import ReviewQueueManager


class TestMasterOrchestrator(unittest.TestCase):

    def setUp(self):
        # Create temporary database and review queue
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_orchestrator.db"
        self.db = InvestigationDatabase(self.db_path)
        self.review_queue = ReviewQueueManager()
        self.orchestrator = MasterOrchestrator(
            db_path=self.db_path,
            review_queue=self.review_queue,
        )

    def tearDown(self):
        self.orchestrator.close()
        self.db.close()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_single_transaction_clean_match(self):
        """Clean transaction with 0 discrepancies should auto-approve without agent overhead."""
        po_data = {
            "purchase_order_number": "PO-CLEAN-001",
            "vendor_name": "Acme Supplies",
            "currency": "USD",
            "lines": [
                {"item_id": "ITEM-1", "description": "Widget A", "quantity": 10, "unit_price": "50.00", "total_price": "500.00"}
            ],
            "subtotal": "500.00",
            "tax": "50.00",
            "total_amount": "550.00",
        }
        invoice_data = {
            "invoice_number": "INV-CLEAN-001",
            "purchase_order_number": "PO-CLEAN-001",
            "vendor_name": "Acme Supplies",
            "currency": "USD",
            "lines": [
                {"item_id": "ITEM-1", "description": "Widget A", "quantity": 10, "unit_price": "50.00", "total_price": "500.00"}
            ],
            "subtotal": "500.00",
            "tax": "50.00",
            "total_amount": "550.00",
        }
        receipt_data = [{
            "receipt_number": "REC-CLEAN-001",
            "purchase_order_number": "PO-CLEAN-001",
            "vendor_name": "Acme Supplies",
            "lines": [
                {"item_id": "ITEM-1", "description": "Widget A", "quantity_delivered": 10}
            ]
        }]

        result: TransactionResult = self.orchestrator.process_transaction(
            po_data=po_data,
            invoice_data=invoice_data,
            receipt_data_list=receipt_data,
            case_id="TRX-CLEAN-001",
        )

        self.assertEqual(result.case_id, "TRX-CLEAN-001")
        self.assertEqual(result.discrepancy_count, 0)
        self.assertEqual(result.recommendation, "APPROVE_PAYMENT")
        self.assertFalse(result.requires_human_review)

        # Verify review queue auto-approval record
        metrics = self.review_queue.get_metrics()
        self.assertEqual(metrics["auto_approved_count"], 1)
        self.assertEqual(metrics["pending_count"], 0)

        # Verify DB persistence
        db_case = self.db.get_investigation("TRX-CLEAN-001")
        self.assertIsNotNone(db_case)
        self.assertEqual(db_case["recommendation"], "APPROVE_PAYMENT")

    def test_single_transaction_discrepancy_triggers_agent(self):
        """Transaction with price variance triggers agent, gathers evidence, and routes to review queue."""
        po_data = {
            "purchase_order_number": "PO-DISC-002",
            "vendor_name": "Apex Tooling",
            "currency": "USD",
            "lines": [
                {"item_id": "DRILL-01", "description": "Precision Bit", "quantity": 5, "unit_price": "100.00", "total_price": "500.00"}
            ],
            "subtotal": "500.00",
            "tax": "50.00",
            "total_amount": "550.00",
        }
        # Invoice billed $120.00 instead of $100.00
        invoice_data = {
            "invoice_number": "INV-DISC-002",
            "purchase_order_number": "PO-DISC-002",
            "vendor_name": "Apex Tooling",
            "currency": "USD",
            "lines": [
                {"item_id": "DRILL-01", "description": "Precision Bit", "quantity": 5, "unit_price": "120.00", "total_price": "600.00"}
            ],
            "subtotal": "600.00",
            "tax": "60.00",
            "total_amount": "660.00",
        }
        receipt_data = [{
            "receipt_number": "REC-DISC-002",
            "purchase_order_number": "PO-DISC-002",
            "vendor_name": "Apex Tooling",
            "lines": [
                {"item_id": "DRILL-01", "description": "Precision Bit", "quantity_delivered": 5}
            ]
        }]

        result: TransactionResult = self.orchestrator.process_transaction(
            po_data=po_data,
            invoice_data=invoice_data,
            receipt_data_list=receipt_data,
            case_id="TRX-DISC-002",
        )

        self.assertEqual(result.case_id, "TRX-DISC-002")
        self.assertGreater(result.discrepancy_count, 0)
        self.assertEqual(result.recommendation, "REQUEST_CREDIT_MEMO")
        self.assertTrue(result.requires_human_review)
        self.assertIsNotNone(result.investigation_result)

        # Verify evidence was gathered
        evidence_list = result.investigation_result.get("evidence", [])
        self.assertGreater(len(evidence_list), 0)

        # Verify review queue contains pending case
        metrics = self.review_queue.get_metrics()
        self.assertEqual(metrics["pending_count"], 1)

    def test_process_files_assembly_line_with_real_documents(self):
        """Processes raw files from dataset through classifier, extractor, validator, reconciler, and agent."""
        mock_recon_dir = ROOT / "dataset" / "mock_reconciliation"
        po_file = mock_recon_dir / "purchase_orders" / "TRX_1789455825_001_po.txt"
        inv_file = mock_recon_dir / "invoices" / "TRX_1789455825_001_invoice.txt"
        rcpt_file = mock_recon_dir / "receipts" / "TRX_1789455825_001_receipt.txt"

        if not (po_file.exists() and inv_file.exists() and rcpt_file.exists()):
            self.skipTest("Mock reconciliation dataset files not found.")

        # Pass the 3 files in mixed order
        input_files = [rcpt_file, po_file, inv_file]

        report: OrchestrationReport = self.orchestrator.process_files(input_files)

        self.assertEqual(report.total_documents, 3)
        self.assertEqual(report.total_transactions, 1)
        self.assertEqual(report.matched_clean, 1)
        self.assertEqual(report.discrepancies_flagged, 0)
        self.assertEqual(len(report.transactions), 1)

        tx = report.transactions[0]
        self.assertEqual(tx.recommendation, "APPROVE_PAYMENT")
        self.assertFalse(tx.requires_human_review)

    def test_process_batch_with_clean_and_discrepant_cases(self):
        """Processes mixed files from multiple transactions: clean and discrepant."""
        mock_recon_dir = ROOT / "dataset" / "mock_reconciliation"
        # Case 001 is clean PERFECT_MATCH, Case 002 is QUANTITY_SHORTAGE
        files = [
            mock_recon_dir / "purchase_orders" / "TRX_1789455825_001_po.txt",
            mock_recon_dir / "invoices" / "TRX_1789455825_001_invoice.txt",
            mock_recon_dir / "receipts" / "TRX_1789455825_001_receipt.txt",
            mock_recon_dir / "purchase_orders" / "TRX_1789455825_002_po.txt",
            mock_recon_dir / "invoices" / "TRX_1789455825_002_invoice.txt",
            mock_recon_dir / "receipts" / "TRX_1789455825_002_receipt.txt",
        ]

        if not all(f.exists() for f in files):
            self.skipTest("Mock reconciliation dataset files not found.")

        report: OrchestrationReport = self.orchestrator.process_files(files)

        self.assertEqual(report.total_documents, 6)
        self.assertEqual(report.total_transactions, 2)
        self.assertEqual(report.matched_clean, 1)
        self.assertEqual(report.discrepancies_flagged, 1)
        self.assertEqual(report.investigated_by_agent, 1)
        self.assertEqual(report.sent_to_review_queue, 1)

    def test_content_based_linking_with_arbitrary_filenames(self):
        """
        Critical test: Verifies that arbitrary filenames with NO common prefixes
        are grouped correctly solely by document content relationships.
        """
        temp_dir = Path(self.temp_dir.name)
        
        # 1. PO file with arbitrary filename
        po_path = temp_dir / "PO_unrelated_filename.txt"
        po_path.write_text("""================================================================================
PURCHASE ORDER
================================================================================
PO Number: PO-84721
Date: 2024-04-10
Payment Terms: Net 30

VENDOR: Allied Manufacturing Corp
Address: 100 Industrial Parkway, Chicago, IL

BILL TO:
Acme Corporation

--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                        QTY    UNIT PRICE     TOTAL
--------------------------------------------------------------------------------
ITM-88           Hydraulic Cylinder                   5       $200.00  $1,000.00
--------------------------------------------------------------------------------
                                                        SUBTOTAL:     $1,000.00
                                                        TAX (0.0%):       $0.00
                                                        GRAND TOTAL:  $1,000.00
================================================================================
""", encoding="utf-8")

        # 2. Invoice file with completely different filename
        inv_path = temp_dir / "invoice_random_alpha.txt"
        inv_path.write_text("""================================================================================
INVOICE
================================================================================
Invoice Number: INV-99301
Date: 2024-04-15
PO Reference: PO-84721

SUPPLIER: Allied Manufacturing Corp
Address: 100 Industrial Parkway, Chicago, IL

BILL TO:
Acme Corporation

--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                        QTY    UNIT PRICE     TOTAL
--------------------------------------------------------------------------------
ITM-88           Hydraulic Cylinder                   5       $200.00  $1,000.00
--------------------------------------------------------------------------------
                                                        SUBTOTAL:     $1,000.00
                                                        TAX (0.0%):       $0.00
                                                        GRAND TOTAL:  $1,000.00
================================================================================
""", encoding="utf-8")

        # 3. Delivery receipt with completely different filename
        rcpt_path = temp_dir / "dock_receiving_slip.txt"
        rcpt_path.write_text("""================================================================================
DELIVERY RECEIPT
================================================================================
Receipt Number: REC-77401
Delivery Date: 2024-04-12
PO Reference: PO-84721

SUPPLIER: Allied Manufacturing Corp
CARRIER: Express Freight
TRACKING: TRK-990021

--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                   ORDERED   DELIVERED       STATUS
--------------------------------------------------------------------------------
ITM-88           Hydraulic Cylinder                  5           5     COMPLETE
--------------------------------------------------------------------------------
Received in good condition.
Receiver: J. Warehouse
================================================================================
""", encoding="utf-8")

        # Process arbitrary files together
        input_files = [inv_path, rcpt_path, po_path]
        report = self.orchestrator.process_files(input_files)

        # Must group into exactly 1 transaction case based on content PO reference PO-84721!
        self.assertEqual(report.total_documents, 3)
        self.assertEqual(report.total_transactions, 1)
        self.assertEqual(report.matched_clean, 1)
        self.assertEqual(report.discrepancies_flagged, 0)

        tx = report.transactions[0]
        self.assertEqual(tx.case_id, "PO-84721")
        self.assertEqual(tx.recommendation, "APPROVE_PAYMENT")
        self.assertFalse(tx.requires_human_review)

    def test_standalone_invoice_with_missing_po_reference(self):
        """
        Verifies that an invoice omitting PO reference forms an unlinked case,
        flags missing PO reference, and triggers buyer escalation.
        """
        temp_dir = Path(self.temp_dir.name)
        inv_path = temp_dir / "invoice_orphan_no_po.txt"
        inv_path.write_text("""================================================================================
INVOICE
================================================================================
Invoice Number: INV-NO-PO-123
Date: 2024-04-18

SUPPLIER: Unknown Vendor Services

--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                        QTY    UNIT PRICE     TOTAL
--------------------------------------------------------------------------------
MISC-01          Consulting Services                 1       $800.00    $800.00
--------------------------------------------------------------------------------
                                                        SUBTOTAL:       $800.00
                                                        GRAND TOTAL:    $800.00
================================================================================
""", encoding="utf-8")

        report = self.orchestrator.process_files([inv_path])

        self.assertEqual(report.total_documents, 1)
        self.assertEqual(report.total_transactions, 1)
        self.assertEqual(report.discrepancies_flagged, 1)

        tx = report.transactions[0]
        self.assertEqual(tx.case_id, "CASE_INV-NO-PO-123")
        self.assertTrue(tx.requires_human_review)
        self.assertIn(tx.recommendation, ("ESCALATE_TO_BUYER", "REJECT_INVOICE"))


if __name__ == "__main__":
    print("\n============================================================")
    print("RUNNING MASTER ORCHESTRATION PIPELINE TEST SUITE")
    print("============================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMasterOrchestrator)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("============================================================")
        print("ALL MASTER ORCHESTRATION PIPELINE TESTS PASSED!")
        print("============================================================\n")
    else:
        sys.exit(1)
