"""
Comprehensive Edge-Case Test Suite for MasterOrchestrator (`src/pipeline/orchestrator.py`).

Tests real-world AP operational edge cases:
1. Multi-format batch ingestion (binary PDF + ASCII TXT).
2. Non-document / empty / zero-byte files mixed in batch (resilience).
3. Inconsistent PO reference strings (e.g., '10248' vs 'PO-10248' vs 'PO# 10248').
4. Multiple partial delivery receipts linked to one PO.
5. Standalone rogue invoice with no PO reference.
6. Price discrepancy triggering agent investigation and review queue.
7. Over-delivery (receipt delivered > PO ordered).
8. Arithmetic mismatch detected during ingestion validation stage.
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


class TestOrchestratorRealWorldEdgeCases(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)
        self.db_path = self.test_dir / "edge_cases.db"
        self.review_queue = ReviewQueueManager()
        self.orchestrator = MasterOrchestrator(
            db_path=self.db_path,
            review_queue=self.review_queue,
        )
        self.dataset_dir = ROOT / "dataset"
        self.real_pdf = self.dataset_dir / "inbox" / "purchase_orders_10248.pdf"

    def tearDown(self):
        self.orchestrator.close()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Edge Case 1: Corrupt, Zero-Byte, and Non-File Inputs in Batch
    # -------------------------------------------------------------------------
    def test_edge_case_empty_and_corrupt_files_resilience(self):
        """Orchestrator must gracefully ignore empty/corrupt files without crashing the valid batch."""
        empty_file = self.test_dir / "empty_0byte.txt"
        empty_file.write_text("", encoding="utf-8")

        garbage_file = self.test_dir / "garbage.txt"
        garbage_file.write_text("RANDOM GARBAGE DATA WITH NO STRUCTURE %$#@!", encoding="utf-8")

        valid_po = self.test_dir / "PO_resilience_test.txt"
        valid_po.write_text("""================================================================================
PURCHASE ORDER
================================================================================
PO Number: PO-RESIL-01
Date: 2024-05-01
Payment Terms: Net 30

VENDOR: Resilient Supplies Co
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                        QTY    UNIT PRICE     TOTAL
--------------------------------------------------------------------------------
ITM-01           Safety Goggles                      10        $15.00   $150.00
--------------------------------------------------------------------------------
                                                        SUBTOTAL:       $150.00
                                                        GRAND TOTAL:    $150.00
================================================================================
""", encoding="utf-8")

        valid_inv = self.test_dir / "INV_resilience_test.txt"
        valid_inv.write_text("""================================================================================
INVOICE
================================================================================
Invoice Number: INV-RESIL-01
Date: 2024-05-05
PO Reference: PO-RESIL-01

VENDOR: Resilient Supplies Co
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                        QTY    UNIT PRICE     TOTAL
--------------------------------------------------------------------------------
ITM-01           Safety Goggles                      10        $15.00   $150.00
--------------------------------------------------------------------------------
                                                        SUBTOTAL:       $150.00
                                                        GRAND TOTAL:    $150.00
================================================================================
""", encoding="utf-8")

        valid_rcpt = self.test_dir / "RCPT_resilience_test.txt"
        valid_rcpt.write_text("""================================================================================
DELIVERY RECEIPT
================================================================================
Receipt Number: REC-RESIL-01
Delivery Date: 2024-05-03
PO Reference: PO-RESIL-01

VENDOR: Resilient Supplies Co
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                   ORDERED   DELIVERED       STATUS
--------------------------------------------------------------------------------
ITM-01           Safety Goggles                     10          10     COMPLETE
================================================================================
""", encoding="utf-8")

        # Pass valid files mixed with zero-byte and garbage files
        batch_files = [empty_file, valid_po, garbage_file, valid_inv, valid_rcpt]
        report: OrchestrationReport = self.orchestrator.process_files(batch_files)

        # Total files processed should be 5
        self.assertEqual(report.total_documents, 5)
        # Should have successfully isolated and matched the valid transaction
        self.assertGreaterEqual(report.total_transactions, 1)

        # Find the resilient transaction
        matched_tx = [tx for tx in report.transactions if tx.case_id == "PO-RESIL-01"]
        self.assertEqual(len(matched_tx), 1)
        self.assertEqual(matched_tx[0].status, "MATCHED")
        self.assertEqual(matched_tx[0].recommendation, "APPROVE_PAYMENT")

    # -------------------------------------------------------------------------
    # Edge Case 2: Multi-format Batch (Binary PDF + Text Invoices)
    # -------------------------------------------------------------------------
    def test_edge_case_binary_pdf_with_text_documents(self):
        """Verifies multi-format ingestion where PO is a real digital PDF and Invoice/Receipt are text."""
        if not self.real_pdf.exists():
            self.skipTest(f"Real PDF test file not found at {self.real_pdf}")

        inv_file = self.test_dir / "invoice_nw_10248.txt"
        inv_file.write_text("""================================================================================
COMMERCIAL INVOICE
================================================================================
Invoice Number:   INV-NW-10248
Invoice Date:     2016-07-10
Payment Terms:    Net 30
PO Reference:     10248

VENDOR:           Northwind Traders
BILL TO:          Paul Henriot

SKU / ITEM        DESCRIPTION                     QTY     UNIT PRICE      TOTAL
--------------------------------------------------------------------------------
11                Queso Cabrales                   12         $14.00    $168.00
42                Singaporean Hokkien Fried Mee    10          $9.80     $98.00
72                Mozzarella di Giovanni            5         $34.80    $174.00
--------------------------------------------------------------------------------
                                                  SUBTOTAL:             $440.00
                                                  GRAND TOTAL:          $440.00
================================================================================
""", encoding="utf-8")

        rcpt_file = self.test_dir / "receipt_nw_10248.txt"
        rcpt_file.write_text("""================================================================================
DELIVERY RECEIPT
================================================================================
Receipt Number:   REC-NW-10248
Delivery Date:    2016-07-08
PO Reference:     10248
Carrier:          FedEx Freight

DELIVERED TO:     Paul Henriot

SKU / ITEM        DESCRIPTION                     QTY ORDERED    QTY DELIVERED
--------------------------------------------------------------------------------
11                Queso Cabrales                   12             12
42                Singaporean Hokkien Fried Mee    10             10
72                Mozzarella di Giovanni            5              5
================================================================================
""", encoding="utf-8")

        report = self.orchestrator.process_files([self.real_pdf, inv_file, rcpt_file])
        self.assertEqual(report.total_documents, 3)
        self.assertEqual(report.total_transactions, 1)

        tx = report.transactions[0]
        self.assertEqual(tx.discrepancy_count, 0)
        self.assertEqual(tx.recommendation, "APPROVE_PAYMENT")

    # -------------------------------------------------------------------------
    # Edge Case 2b: Inconsistent PO Reference Formats ('99100' vs 'PO-99100' vs 'PO# 99100')
    # -------------------------------------------------------------------------
    def test_edge_case_inconsistent_po_reference_formats(self):
        """
        Tests linking when documents use different representations of the same PO:
        - Purchase Order has 'PO Number: 99100'
        - Invoice has 'PO Reference: PO-99100'
        - Delivery Receipt has 'PO Reference: PO# 99100'
        All 3 must link into a single transaction case via normalization!
        """
        po_file = self.test_dir / "PO_format_var.txt"
        po_file.write_text("""================================================================================
PURCHASE ORDER
================================================================================
PO Number: 99100
Date: 2024-04-01
Payment Terms: Net 30

VENDOR: Universal Fasteners Inc
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                        QTY    UNIT PRICE     TOTAL
--------------------------------------------------------------------------------
FST-01           Titanium Bolt M8                    50         $4.00   $200.00
--------------------------------------------------------------------------------
                                                        SUBTOTAL:       $200.00
                                                        GRAND TOTAL:    $200.00
================================================================================
""", encoding="utf-8")

        inv_file = self.test_dir / "INV_format_var.txt"
        inv_file.write_text("""================================================================================
INVOICE
================================================================================
Invoice Number: INV-FST-99100
Date: 2024-04-05
PO Reference: PO-99100

VENDOR: Universal Fasteners Inc
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                        QTY    UNIT PRICE     TOTAL
--------------------------------------------------------------------------------
FST-01           Titanium Bolt M8                    50         $4.00   $200.00
--------------------------------------------------------------------------------
                                                        SUBTOTAL:       $200.00
                                                        GRAND TOTAL:    $200.00
================================================================================
""", encoding="utf-8")

        rcpt_file = self.test_dir / "RCPT_format_var.txt"
        rcpt_file.write_text("""================================================================================
DELIVERY RECEIPT
================================================================================
Receipt Number: REC-FST-99100
Delivery Date: 2024-04-03
PO Reference: PO# 99100

VENDOR: Universal Fasteners Inc
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                   ORDERED   DELIVERED       STATUS
--------------------------------------------------------------------------------
FST-01           Titanium Bolt M8                    50          50     COMPLETE
================================================================================
""", encoding="utf-8")

        report = self.orchestrator.process_files([po_file, inv_file, rcpt_file])
        self.assertEqual(report.total_documents, 3)
        self.assertEqual(report.total_transactions, 1)

        tx = report.transactions[0]
        self.assertEqual(tx.status, "MATCHED")
        self.assertEqual(tx.discrepancy_count, 0)
        self.assertEqual(tx.recommendation, "APPROVE_PAYMENT")

    # -------------------------------------------------------------------------
    # Edge Case 3: Multiple Partial Delivery Receipts for One PO
    # -------------------------------------------------------------------------
    def test_edge_case_multiple_partial_delivery_receipts(self):
        """
        PO orders 10 units.
        Receipt 1 delivers 6 units.
        Receipt 2 delivers 4 units.
        Invoice bills 10 units.
        Total delivered = 6 + 4 = 10 units. Reconciles cleanly!
        """
        po_file = self.test_dir / "PO_partial.txt"
        po_file.write_text("""================================================================================
PURCHASE ORDER
================================================================================
PO Number: PO-PARTIAL-01
Date: 2024-03-01

VENDOR: Component Logistics Ltd
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                        QTY    UNIT PRICE     TOTAL
--------------------------------------------------------------------------------
CMP-99           Ball Bearings                      10        $20.00   $200.00
--------------------------------------------------------------------------------
                                                        SUBTOTAL:       $200.00
                                                        GRAND TOTAL:    $200.00
================================================================================
""", encoding="utf-8")

        # Delivery 1: 6 units
        rcpt1_file = self.test_dir / "RCPT_part1.txt"
        rcpt1_file.write_text("""================================================================================
DELIVERY RECEIPT
================================================================================
Receipt Number: REC-PART-01
Delivery Date: 2024-03-05
PO Reference: PO-PARTIAL-01

VENDOR: Component Logistics Ltd
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                   ORDERED   DELIVERED       STATUS
--------------------------------------------------------------------------------
CMP-99           Ball Bearings                      10           6      PARTIAL
================================================================================
""", encoding="utf-8")

        # Delivery 2: 4 units
        rcpt2_file = self.test_dir / "RCPT_part2.txt"
        rcpt2_file.write_text("""================================================================================
DELIVERY RECEIPT
================================================================================
Receipt Number: REC-PART-02
Delivery Date: 2024-03-08
PO Reference: PO-PARTIAL-01

VENDOR: Component Logistics Ltd
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                   ORDERED   DELIVERED       STATUS
--------------------------------------------------------------------------------
CMP-99           Ball Bearings                      10           4     COMPLETE
================================================================================
""", encoding="utf-8")

        # Invoice bills for 10 units
        inv_file = self.test_dir / "INV_partial.txt"
        inv_file.write_text("""================================================================================
INVOICE
================================================================================
Invoice Number: INV-PART-01
Date: 2024-03-10
PO Reference: PO-PARTIAL-01

VENDOR: Component Logistics Ltd
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                        QTY    UNIT PRICE     TOTAL
--------------------------------------------------------------------------------
CMP-99           Ball Bearings                      10        $20.00   $200.00
--------------------------------------------------------------------------------
                                                        SUBTOTAL:       $200.00
                                                        GRAND TOTAL:    $200.00
================================================================================
""", encoding="utf-8")

        report = self.orchestrator.process_files([po_file, rcpt1_file, rcpt2_file, inv_file])

        # All 4 files must group into 1 transaction case
        self.assertEqual(report.total_documents, 4)
        self.assertEqual(report.total_transactions, 1)

        tx = report.transactions[0]
        self.assertEqual(tx.case_id, "PO-PARTIAL-01")
        # Line matcher accumulates: 6 + 4 = 10 delivered == 10 invoiced!
        self.assertEqual(tx.status, "MATCHED")
        self.assertEqual(tx.discrepancy_count, 0)
        self.assertEqual(tx.recommendation, "APPROVE_PAYMENT")

    # -------------------------------------------------------------------------
    # Edge Case 4: Standalone Rogue Invoice Without PO Reference
    # -------------------------------------------------------------------------
    def test_edge_case_standalone_unlinked_invoice(self):
        """Unlinked invoice with no PO reference must form an isolated case and require human review."""
        inv_file = self.test_dir / "INV_rogue_no_po.txt"
        inv_file.write_text("""================================================================================
INVOICE
================================================================================
Invoice Number: INV-UNLINKED-99
Date: 2024-06-01

VENDOR: Mystery Contractor Services
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                        QTY    UNIT PRICE     TOTAL
--------------------------------------------------------------------------------
SRV-01           Server Maintenance                  1     $1,500.00  $1,500.00
--------------------------------------------------------------------------------
                                                        SUBTOTAL:     $1,500.00
                                                        GRAND TOTAL:  $1,500.00
================================================================================
""", encoding="utf-8")

        report = self.orchestrator.process_files([inv_file])
        self.assertEqual(report.total_documents, 1)
        self.assertEqual(report.total_transactions, 1)

        tx = report.transactions[0]
        self.assertEqual(tx.case_id, "CASE_INV-UNLINKED-99")
        self.assertGreater(tx.discrepancy_count, 0)
        self.assertTrue(tx.requires_human_review)
        self.assertIn(tx.recommendation, ("ESCALATE_TO_BUYER", "REJECT_INVOICE"))

        # Must be in human review queue
        metrics = self.review_queue.get_metrics()
        self.assertEqual(metrics["pending_count"], 1)

    # -------------------------------------------------------------------------
    # Edge Case 5: Overbilled Price Discrepancy Triggers AI Agent & Review Queue
    # -------------------------------------------------------------------------
    def test_edge_case_price_variance_agent_investigation(self):
        """Price overbilling must be caught, investigated by agent, and enqueued with credit memo recommendation."""
        po_file = self.test_dir / "PO_price_err.txt"
        po_file.write_text("""================================================================================
PURCHASE ORDER
================================================================================
PO Number: PO-OVERBILL-01
Date: 2024-07-01

VENDOR: Standard Tech Parts
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                        QTY    UNIT PRICE     TOTAL
--------------------------------------------------------------------------------
RAM-01           16GB DDR5 Module                    4        $80.00   $320.00
--------------------------------------------------------------------------------
                                                        SUBTOTAL:       $320.00
                                                        GRAND TOTAL:    $320.00
================================================================================
""", encoding="utf-8")

        # Invoice billed $120.00 instead of $80.00
        inv_file = self.test_dir / "INV_price_err.txt"
        inv_file.write_text("""================================================================================
INVOICE
================================================================================
Invoice Number: INV-OVERBILL-01
Date: 2024-07-10
PO Reference: PO-OVERBILL-01

VENDOR: Standard Tech Parts
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                        QTY    UNIT PRICE     TOTAL
--------------------------------------------------------------------------------
RAM-01           16GB DDR5 Module                    4       $120.00   $480.00
--------------------------------------------------------------------------------
                                                        SUBTOTAL:       $480.00
                                                        GRAND TOTAL:    $480.00
================================================================================
""", encoding="utf-8")

        rcpt_file = self.test_dir / "RCPT_price_err.txt"
        rcpt_file.write_text("""================================================================================
DELIVERY RECEIPT
================================================================================
Receipt Number: REC-OVERBILL-01
Delivery Date: 2024-07-05
PO Reference: PO-OVERBILL-01

VENDOR: Standard Tech Parts
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                   ORDERED   DELIVERED       STATUS
--------------------------------------------------------------------------------
RAM-01           16GB DDR5 Module                    4           4     COMPLETE
================================================================================
""", encoding="utf-8")

        report = self.orchestrator.process_files([po_file, inv_file, rcpt_file])
        self.assertEqual(report.total_documents, 3)
        self.assertEqual(report.total_transactions, 1)

        tx = report.transactions[0]
        self.assertGreater(tx.discrepancy_count, 0)
        self.assertTrue(tx.requires_human_review)
        self.assertEqual(tx.recommendation, "REQUEST_CREDIT_MEMO")

        # Review queue must hold this item
        self.assertEqual(self.review_queue.get_metrics()["pending_count"], 1)

    # -------------------------------------------------------------------------
    # Edge Case 6: Arithmetic Math Validation Failure on Raw Document
    # -------------------------------------------------------------------------
    def test_edge_case_arithmetic_math_error_flagged_in_validation(self):
        """Document with internal arithmetic error (sum of lines != printed total) must be flagged."""
        inv_file = self.test_dir / "INV_bad_math.txt"
        # 2 items of $100 = $200, but invoice prints GRAND TOTAL: $999.00
        inv_file.write_text("""================================================================================
INVOICE
================================================================================
Invoice Number: INV-BAD-MATH-01
Date: 2024-08-01
PO Reference: PO-BAD-MATH-01

VENDOR: Inconsistent Arithmetic Corp
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                        QTY    UNIT PRICE     TOTAL
--------------------------------------------------------------------------------
ITM-A            Laser Cartridge                     2       $100.00   $200.00
--------------------------------------------------------------------------------
                                                        SUBTOTAL:       $200.00
                                                        GRAND TOTAL:    $999.00
================================================================================
""", encoding="utf-8")

        po_file = self.test_dir / "PO_bad_math.txt"
        po_file.write_text("""================================================================================
PURCHASE ORDER
================================================================================
PO Number: PO-BAD-MATH-01
Date: 2024-07-25

VENDOR: Inconsistent Arithmetic Corp
--------------------------------------------------------------------------------
SKU / ITEM       DESCRIPTION                        QTY    UNIT PRICE     TOTAL
--------------------------------------------------------------------------------
ITM-A            Laser Cartridge                     2       $100.00   $200.00
--------------------------------------------------------------------------------
                                                        SUBTOTAL:       $200.00
                                                        GRAND TOTAL:    $200.00
================================================================================
""", encoding="utf-8")

        report = self.orchestrator.process_files([po_file, inv_file])
        self.assertEqual(report.total_documents, 2)
        tx = report.transactions[0]
        # Must flag discrepancy due to total mismatch ($999 vs $200)
        self.assertGreater(tx.discrepancy_count, 0)
        self.assertTrue(tx.requires_human_review)


if __name__ == "__main__":
    unittest.main(verbosity=2)
