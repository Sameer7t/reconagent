"""
Unified Extraction Boundary for ReconAgent.

Provides a decoupled extraction interface that coordinates between:
- Deterministic structured text parsers (mock format, Northwind PO PDF format)
- Multimodal / Vision LLM extractors (Gemini 3.5 Flash Lite) for scanned/unstructured files
- Pydantic schema normalization

This decouples orchestrators and upstream classifiers from file format specifics,
regex parsing, or remote API calling details.
"""

import re
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional, Union, Dict, Any, List

from schemas.document_classification import DocumentType
from ingestion.document_ingestion import IngestedDocument, ingest_document
from extraction.mock_text_extractor import (
    extract_mock_purchase_order,
    extract_mock_invoice,
    extract_mock_receipt,
)

logger = logging.getLogger("UnifiedExtractor")


def _to_decimal(val_str: Optional[Any]) -> Optional[Decimal]:
    """Safely converts input to Decimal."""
    if val_str is None:
        return None
    clean = re.sub(r'[\$,]', '', str(val_str)).strip()
    try:
        return Decimal(clean)
    except (InvalidOperation, ValueError):
        return None


def _extract_northwind_po_pdf(text: str, file_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """
    Deterministically extracts structured PO data from Northwind-style digital PDF text.
    Handles layout:
      Purchase Orders
      Order ID Order Date Customer Name
      10248 2016-07-04 Paul Henriot
      Products
      Product ID: Product: Quantity: Unit Price:
      11 Queso Cabrales 12 14
    """
    if "Purchase Orders" not in text and "Order ID" not in text:
        return None

    # Match header line
    m_head = re.search(
        r"Order ID\s+Order Date\s+Customer Name\s*\n\s*(\S+)\s+(\S+)\s+(.+)",
        text,
        re.IGNORECASE
    )
    if not m_head:
        return None

    po_number = m_head.group(1).strip()
    order_date = m_head.group(2).strip()
    customer_name = m_head.group(3).strip()

    # Extract products table
    items: List[Dict[str, Any]] = []
    lines = text.splitlines()
    in_products = False

    for line in lines:
        line_s = line.strip()
        if "Product ID:" in line_s or "Products" in line_s:
            in_products = True
            continue
        if line_s.startswith("Page ") or line_s.startswith("==="):
            continue
        if in_products:
            # Pattern: <id> <product name> <qty> <unit price>
            m_item = re.match(r"^\s*(\d+)\s+(.+?)\s+(\d+)\s+([0-9\.]+)\s*$", line)
            if m_item:
                p_code = m_item.group(1).strip()
                p_desc = m_item.group(2).strip()
                qty = _to_decimal(m_item.group(3))
                unit_price = _to_decimal(m_item.group(4))
                line_total = (qty * unit_price) if (qty is not None and unit_price is not None) else None

                items.append({
                    "product_code": p_code,
                    "description": p_desc,
                    "quantity": qty,
                    "unit_price": unit_price,
                    "line_total": line_total,
                })

    subtotal = sum((item["line_total"] for item in items if item.get("line_total") is not None), Decimal("0.00"))
    
    return {
        "file_name": file_path.name if file_path else None,
        "transaction_id": None,
        "purchase_order_number": po_number,
        "vendor_name": "Northwind Traders",
        "customer_name": customer_name,
        "order_date": order_date,
        "currency": "USD",
        "payment_terms": "Net 30",
        "items": items,
        "subtotal": subtotal,
        "discount": Decimal("0.00"),
        "shipping": Decimal("0.00"),
        "tax": Decimal("0.00"),
        "total": subtotal,
    }


def extract_document(
    document: Union[IngestedDocument, str, Path],
    document_type: Union[DocumentType, str],
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Unified entry point for document extraction.

    Coordinates between local high-precision text parsers (instant, zero cost)
    and Gemini Multimodal / File API extractors (for unstructured/scanned files).

    Args:
        document: IngestedDocument instance, or path to physical file.
        document_type: Classified DocumentType enum or string ("invoice", "purchase_order", "receipt").
        client: Optional Gemini API client for LLM / vision extraction fallback.

    Returns:
        Structured data dictionary conforming to Pydantic schemas.
    """
    # 1. Normalize IngestedDocument
    if isinstance(document, IngestedDocument):
        doc = document
    else:
        doc = ingest_document(document, extract_text=True)

    # 2. Normalize document type
    if isinstance(document_type, DocumentType):
        doc_type_str = document_type.value.lower()
    else:
        doc_type_str = str(document_type).lower().strip()

    logger.debug(f"[UnifiedExtractor] Extracting '{doc.file_name}' as {doc_type_str} (has_text={doc.has_text})")

    def _do_extract() -> Dict[str, Any]:
        # -------------------------------------------------------------------------
        # A. PURCHASE ORDER EXTRACTION
        # -------------------------------------------------------------------------
        if doc_type_str in ("purchase_order", "po"):
            if doc.has_text and doc.text_content:
                # Try mock ASCII format
                extracted = extract_mock_purchase_order(doc.text_content, doc.file_path)
                if extracted and (extracted.get("items") or extracted.get("purchase_order_number")):
                    return extracted

                # Try Northwind tabular PDF format
                nw_extracted = _extract_northwind_po_pdf(doc.text_content, doc.file_path)
                if nw_extracted and nw_extracted.get("items"):
                    return nw_extracted

            # If digital text parser didn't produce items, or file is scanned, fallback to Gemini
            if client is not None:
                try:
                    from extraction.process_purchase_orders import extract_single_purchase_order
                    po_obj = extract_single_purchase_order(client, doc.file_path)
                    if po_obj:
                        return po_obj.model_dump()
                except Exception as exc:
                    logger.error(f"[UnifiedExtractor] Gemini PO extraction failed on '{doc.file_name}': {exc}")

            # Return whatever partial structure mock extractor returned or empty dict
            return extract_mock_purchase_order(doc.text_content or "", doc.file_path) if doc.text_content else {}

        # -------------------------------------------------------------------------
        # B. INVOICE EXTRACTION
        # -------------------------------------------------------------------------
        elif doc_type_str in ("invoice", "commercial_invoice", "tax_invoice"):
            if doc.has_text and doc.text_content:
                extracted = extract_mock_invoice(doc.text_content, doc.file_path)
                if extracted and (extracted.get("items") or extracted.get("invoice_number")):
                    return extracted

            # If mock format didn't succeed or file is scanned, try Gemini LLM/Vision
            if client is not None:
                try:
                    from extraction.process_invoice import extract_single_invoice
                    inv_obj = extract_single_invoice(client, doc.file_path)
                    if inv_obj:
                        return inv_obj.model_dump()
                except Exception as exc:
                    logger.error(f"[UnifiedExtractor] Gemini Invoice extraction failed on '{doc.file_name}': {exc}")

            return extract_mock_invoice(doc.text_content or "", doc.file_path) if doc.text_content else {}

        # -------------------------------------------------------------------------
        # C. RECEIPT EXTRACTION
        # -------------------------------------------------------------------------
        elif doc_type_str in ("receipt", "delivery_receipt", "packing_slip"):
            if doc.has_text and doc.text_content:
                extracted = extract_mock_receipt(doc.text_content, doc.file_path)
                if extracted and (extracted.get("items") or extracted.get("receipt_number")):
                    return extracted

            # If mock format didn't succeed or file is image/scanned, try Gemini LLM/Vision
            if client is not None:
                try:
                    from extraction.process_receipt import extract_single_receipt
                    rcpt_obj = extract_single_receipt(client, doc.file_path)
                    if rcpt_obj:
                        return rcpt_obj.model_dump()
                except Exception as exc:
                    logger.error(f"[UnifiedExtractor] Gemini Receipt extraction failed on '{doc.file_name}': {exc}")

            return extract_mock_receipt(doc.text_content or "", doc.file_path) if doc.text_content else {}

        # -------------------------------------------------------------------------
        # D. UNKNOWN / UNRECOGNIZED
        # -------------------------------------------------------------------------
        else:
            logger.warning(f"[UnifiedExtractor] Unknown document type '{doc_type_str}' for '{doc.file_name}'")
            return {
                "file_name": doc.file_name,
                "document_type": "unknown",
                "text_preview": (doc.text_content or "")[:200],
            }

    result = _do_extract()
    if isinstance(result, dict):
        result["_source_file"] = str(doc.file_path)
        if "file_name" not in result:
            result["file_name"] = doc.file_name
    return result

