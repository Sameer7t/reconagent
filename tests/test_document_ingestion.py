"""
Comprehensive Test Suite for Document Ingestion Boundary & Real PDF Support.

Verifies:
1. Ingestion of plain text (.txt) files with proper encoding and metadata.
2. Ingestion of binary digital PDF (.pdf) files with pypdf text extraction and page counting.
3. Ingestion error handling for missing, invalid, or corrupted paths.
4. Classification boundary consuming IngestedDocument objects directly.
5. Unified extraction boundary extracting structured data from IngestedDocument objects.
6. MasterOrchestrator running end-to-end over physical PDF documents without file-reading errors.
"""

import os
import sys
import unittest
import tempfile
import shutil
from pathlib import Path
from decimal import Decimal

# Setup project path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from ingestion import IngestedDocument, ingest_document, extract_pdf_text, classify_document
from extraction import extract_document
from schemas.document_classification import DocumentType
from pipeline import MasterOrchestrator


class TestDocumentIngestion(unittest.TestCase):

    def setUp(self):
        self.dataset_root = PROJECT_ROOT / "dataset"
        self.real_pdf_path = self.dataset_root / "inbox" / "purchase_orders_10248.pdf"
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. Plain Text Ingestion
    # -------------------------------------------------------------------------
    def test_ingest_txt_document(self):
        """Verifies ingestion of a plain text file."""
        sample_txt = self.test_dir / "sample_invoice.txt"
        sample_txt.write_text(
            "COMMERCIAL INVOICE\nInvoice Number: INV-8899\nVendor: Acme Corp\nTotal: $500.00\n",
            encoding="utf-8"
        )

        doc: IngestedDocument = ingest_document(sample_txt)
        self.assertEqual(doc.file_type, "txt")
        self.assertEqual(doc.extension, ".txt")
        self.assertTrue(doc.has_text)
        self.assertFalse(doc.is_scanned)
        self.assertEqual(doc.page_count, 1)
        self.assertIn("COMMERCIAL INVOICE", doc.text_content)
        self.assertIn("INV-8899", doc.text_content)
        self.assertGreater(doc.file_size_bytes, 0)
        self.assertEqual(len(doc.get_raw_bytes()), doc.file_size_bytes)

    # -------------------------------------------------------------------------
    # 2. Real Digital PDF Ingestion
    # -------------------------------------------------------------------------
    def test_ingest_real_digital_pdf(self):
        """Verifies ingestion of real binary PDF file using pypdf."""
        if not self.real_pdf_path.exists():
            self.skipTest(f"PDF test file not found at {self.real_pdf_path}")

        doc: IngestedDocument = ingest_document(self.real_pdf_path)
        self.assertEqual(doc.file_type, "pdf")
        self.assertEqual(doc.extension, ".pdf")
        self.assertTrue(doc.has_text)
        self.assertFalse(doc.is_scanned)
        self.assertEqual(doc.page_count, 1)
        self.assertIsNotNone(doc.text_content)
        self.assertIn("Purchase Orders", doc.text_content)
        self.assertIn("10248", doc.text_content)
        self.assertIn("Paul Henriot", doc.text_content)
        self.assertGreater(doc.file_size_bytes, 1000)

        # Standalone extract_pdf_text helper
        text, pages, meta = extract_pdf_text(self.real_pdf_path)
        self.assertEqual(pages, 1)
        self.assertIn("Purchase Orders", text)

    # -------------------------------------------------------------------------
    # 3. Error Handling for Nonexistent or Corrupt Files
    # -------------------------------------------------------------------------
    def test_ingest_missing_file_raises_error(self):
        """Verifies FileNotFoundError when attempting to ingest nonexistent path."""
        nonexistent = self.test_dir / "does_not_exist.pdf"
        with self.assertRaises(FileNotFoundError):
            ingest_document(nonexistent)

    def test_ingest_directory_raises_error(self):
        """Verifies ValueError when passing a directory instead of file."""
        with self.assertRaises(ValueError):
            ingest_document(self.test_dir)

    # -------------------------------------------------------------------------
    # 4. Classification Consuming IngestedDocument
    # -------------------------------------------------------------------------
    def test_classify_document_from_ingested_pdf(self):
        """Verifies classify_document directly consumes IngestedDocument without re-reading."""
        if not self.real_pdf_path.exists():
            self.skipTest(f"PDF test file not found at {self.real_pdf_path}")

        doc = ingest_document(self.real_pdf_path)
        class_res = classify_document(doc)

        self.assertEqual(class_res.document_type, DocumentType.PURCHASE_ORDER)
        self.assertGreaterEqual(class_res.confidence, 0.90)
        self.assertEqual(class_res.file_name, "purchase_orders_10248.pdf")

    # -------------------------------------------------------------------------
    # 5. Extraction Consuming IngestedDocument
    # -------------------------------------------------------------------------
    def test_extract_document_from_ingested_pdf(self):
        """Verifies extract_document extracts structured data from PDF IngestedDocument."""
        if not self.real_pdf_path.exists():
            self.skipTest(f"PDF test file not found at {self.real_pdf_path}")

        doc = ingest_document(self.real_pdf_path)
        extracted = extract_document(doc, DocumentType.PURCHASE_ORDER)

        self.assertIsInstance(extracted, dict)
        self.assertEqual(extracted.get("purchase_order_number"), "10248")
        self.assertEqual(extracted.get("order_date"), "2016-07-04")
        self.assertEqual(extracted.get("customer_name"), "Paul Henriot")
        self.assertIn("items", extracted)
        self.assertGreater(len(extracted["items"]), 0)

        # Check first line item
        first_item = extracted["items"][0]
        self.assertEqual(first_item["product_code"], "11")
        self.assertIn("Queso Cabrales", first_item["description"])
        self.assertEqual(first_item["quantity"], Decimal("12"))
        self.assertEqual(first_item["unit_price"], Decimal("14"))

    # -------------------------------------------------------------------------
    # 6. MasterOrchestrator End-to-End on PDF
    # -------------------------------------------------------------------------
    def test_orchestrator_process_pdf_and_txt_files(self):
        """
        Verifies that MasterOrchestrator processes a physical PDF purchase order
        and corresponding invoice without crashing or attempting invalid binary string reads.
        """
        if not self.real_pdf_path.exists():
            self.skipTest(f"PDF test file not found at {self.real_pdf_path}")

        # Create a matching invoice in test directory referencing PO 10248
        inv_file = self.test_dir / "invoice_for_po_10248.txt"
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

        db_file = self.test_dir / "test_ingestion_inv.db"
        orchestrator = MasterOrchestrator(db_path=db_file)

        try:
            # Process both the real PDF file and the text invoice file together
            report = orchestrator.process_files([self.real_pdf_path, inv_file])

            self.assertEqual(report.total_documents, 2)
            self.assertEqual(report.total_transactions, 1)

            tx = report.transactions[0]
            self.assertEqual(tx.case_id, "10248")
            # In absence of delivery receipt, status is flagged as INCOMPLETE or REVIEW_REQUIRED
            self.assertIn(tx.status, ("INCOMPLETE", "REVIEW_REQUIRED"))
            self.assertIsNotNone(tx.reconciliation_result)

        finally:
            orchestrator.close()

    def test_orchestrator_3way_clean_match_with_pdf(self):
        """
        Verifies that MasterOrchestrator performs a 100% clean 3-way match
        combining a binary PDF purchase order, a text invoice, and a delivery receipt.
        """
        if not self.real_pdf_path.exists():
            self.skipTest(f"PDF test file not found at {self.real_pdf_path}")

        inv_file = self.test_dir / "invoice_po_10248.txt"
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

        rcpt_file = self.test_dir / "receipt_po_10248.txt"
        rcpt_file.write_text("""================================================================================
DELIVERY RECEIPT / PROOF OF DELIVERY
================================================================================
Receipt Number:   RCPT-NW-10248
Delivery Date:    2016-07-08
PO Reference:     10248
Carrier:          FedEx Freight

DELIVERED TO:     Paul Henriot
RECEIVED BY:      Warehouse Staff (Confirmed)

SKU / ITEM        DESCRIPTION                     QTY ORDERED    QTY DELIVERED
--------------------------------------------------------------------------------
11                Queso Cabrales                   12             12
42                Singaporean Hokkien Fried Mee    10             10
72                Mozzarella di Giovanni            5              5
--------------------------------------------------------------------------------
STATUS:           ALL GOODS RECEIVED IN GOOD CONDITION
================================================================================
""", encoding="utf-8")

        db_file = self.test_dir / "test_3way_ingestion.db"
        orchestrator = MasterOrchestrator(db_path=db_file)

        try:
            report = orchestrator.process_files([self.real_pdf_path, inv_file, rcpt_file])

            self.assertEqual(report.total_documents, 3)
            self.assertEqual(report.total_transactions, 1)

            tx = report.transactions[0]
            self.assertEqual(tx.case_id, "10248")
            self.assertEqual(tx.status, "MATCHED")
            self.assertEqual(tx.discrepancy_count, 0)
            self.assertEqual(tx.recommendation, "APPROVE_PAYMENT")
            self.assertFalse(tx.requires_human_review)

        finally:
            orchestrator.close()


if __name__ == "__main__":
    print("\n============================================================")
    print("RUNNING DOCUMENT INGESTION & REAL PDF TEST SUITE")
    print("============================================================")
    unittest.main(verbosity=2)

