"""
High-Precision Structured Text Extractor for Mock Reconciliation Documents.

Extracts structured data from the mock ASCII/text documents in `dataset/mock_reconciliation/`:
- Invoices
- Purchase Orders
- Delivery Receipts

Emits clean dictionary representations that validate cleanly into Pydantic models
(PurchaseOrder, Invoice, Receipt) and seamlessly feed the validation and reconciliation pipelines.
"""
import re
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("MockTextExtractor")


def _to_decimal(val_str: Optional[str]) -> Optional[Decimal]:
    """Safely converts a string to Decimal, stripping currency symbols and commas."""
    if not val_str:
        return None
    clean = re.sub(r'[\$,]', '', str(val_str)).strip()
    try:
        return Decimal(clean)
    except (InvalidOperation, ValueError):
        return None


def _extract_field(pattern: str, text: str) -> Optional[str]:
    """Extracts a regex capture group from text."""
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _clean_id(val: Optional[str]) -> Optional[str]:
    """Cleans extracted document IDs by stripping trailing inline metadata (e.g. Date, Due Date, Terms)."""
    if not val:
        return None
    # Strip any inline trailing fields like "   Date: 2023-10-12" or "   Due Date: ..."
    val = re.split(r'\s{2,}|\s+(?:Date|Due\s+Date|Terms|Payment\s+Terms):', val, flags=re.IGNORECASE)[0].strip()
    if val.upper() in {"[NOT SPECIFIED]", "[NOT PROVIDED]", "NONE", "N/A", "NULL", ""}:
        return None
    return val


def extract_mock_purchase_order(text: str, file_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Parses a mock purchase order text document.
    """
    po_number = _clean_id(_extract_field(r"PO Number:\s*([^\r\n]+)", text))
    order_date = _extract_field(r"(?:PO\s+)?Date:\s*([0-9\-]+)", text)
    terms = _extract_field(r"Payment Terms:\s*([^\r\n]+)", text)
    if terms:
        terms = terms.split("FOB:")[0].strip()

    # Vendor extraction
    vendor_match = re.search(r"(?:VENDOR|SUPPLIER):\s*(.+)", text, re.IGNORECASE)
    vendor_name = vendor_match.group(1).splitlines()[0].strip() if vendor_match else None

    # Line items
    items: List[Dict[str, Any]] = []
    lines = text.splitlines()
    table_started = False

    for line in lines:
        line_s = line.strip()
        if re.search(r"^SKU\b", line_s, re.IGNORECASE) and "DESCRIPTION" in line_s:
            table_started = True
            continue
        if table_started:
            if re.search(r"^(SUBTOTAL|GRAND TOTAL|TOTAL DUE|SHIPPING|TAX|Payment Terms)", line_s, re.IGNORECASE):
                break
            if line_s.startswith("---") or line_s.startswith("===") or not line_s:
                continue

            m = re.search(r"^\s*([A-Za-z0-9\-]+)\s+(.+?)\s*(\d+)\s+[\$]?([0-9,]+\.\d{2})\s+[\$]?([0-9,]+\.\d{2})\s*$", line)
            if m:
                items.append({
                    "product_code": m.group(1).strip(),
                    "description": m.group(2).strip(),
                    "quantity": _to_decimal(m.group(3)),
                    "unit_price": _to_decimal(m.group(4)),
                    "line_total": _to_decimal(m.group(5)),
                })

    subtotal = _to_decimal(_extract_field(r"SUBTOTAL\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text))
    discount = _to_decimal(_extract_field(r"DISCOUNT\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text)) or Decimal("0.00")
    shipping = _to_decimal(_extract_field(r"SHIPPING(?: & HANDLING)?\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text)) or Decimal("0.00")
    tax = _to_decimal(_extract_field(r"TAX.*?\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text)) or Decimal("0.00")
    total = _to_decimal(_extract_field(r"\b(?:GRAND TOTAL|TOTAL DUE|TOTAL)\b\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text))
    transaction_id = _extract_field(r"Transaction ID:\s*([A-Za-z0-9\_]+)", text)
    if not transaction_id and file_path:
        parts = file_path.stem.split("_")
        if len(parts) >= 3 and parts[0] == "TRX":
            transaction_id = "_".join(parts[:3])

    return {
        "file_name": file_path.name if file_path else None,
        "transaction_id": transaction_id,
        "purchase_order_number": po_number,
        "vendor_name": vendor_name,
        "order_date": order_date,
        "currency": "USD",
        "payment_terms": terms,
        "items": items,
        "subtotal": subtotal,
        "discount": discount,
        "shipping": shipping,
        "tax": tax,
        "total": total,
    }


def extract_mock_invoice(text: str, file_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Parses a mock invoice text document.
    """
    invoice_number = _clean_id(_extract_field(r"Invoice Number:\s*([^\r\n]+)", text))
    invoice_date = _extract_field(r"(?:Invoice\s+)?Date:\s*([0-9\-]+)", text)
    po_reference = _clean_id(_extract_field(r"PO Reference:\s*([^\r\n]+)", text))

    # Vendor extraction
    vendor_match = re.search(r"(?:VENDOR|SUPPLIER):\s*(.+)", text, re.IGNORECASE)
    vendor_name = vendor_match.group(1).splitlines()[0].strip() if vendor_match else None

    # Line items
    items: List[Dict[str, Any]] = []
    lines = text.splitlines()
    table_started = False

    for line in lines:
        line_s = line.strip()
        if re.search(r"^SKU\b", line_s, re.IGNORECASE) and "DESCRIPTION" in line_s:
            table_started = True
            continue
        if table_started:
            if re.search(r"^(SUBTOTAL|GRAND TOTAL|TOTAL DUE|SHIPPING|TAX|Payment Terms|ALERT|Note:)", line_s, re.IGNORECASE):
                break
            if line_s.startswith("---") or line_s.startswith("===") or not line_s:
                continue

            m = re.search(r"^\s*([A-Za-z0-9\-]+)\s+(.+?)\s*(\d+)\s+[\$]?([0-9,]+\.\d{2})\s+[\$]?([0-9,]+\.\d{2})\s*$", line)
            if m:
                items.append({
                    "product_code": m.group(1).strip(),
                    "description": m.group(2).strip(),
                    "quantity": _to_decimal(m.group(3)),
                    "unit_price": _to_decimal(m.group(4)),
                    "line_total": _to_decimal(m.group(5)),
                })

    subtotal = _to_decimal(_extract_field(r"SUBTOTAL\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text))
    discount = _to_decimal(_extract_field(r"DISCOUNT\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text)) or Decimal("0.00")
    shipping = _to_decimal(_extract_field(r"SHIPPING(?: & HANDLING)?\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text)) or Decimal("0.00")
    total_tax = _to_decimal(_extract_field(r"TAX.*?\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text)) or Decimal("0.00")
    total = _to_decimal(_extract_field(r"\b(?:GRAND TOTAL|TOTAL DUE|TOTAL)\b\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text))
    transaction_id = _extract_field(r"Transaction ID:\s*([A-Za-z0-9\_]+)", text)
    if not transaction_id and file_path:
        parts = file_path.stem.split("_")
        if len(parts) >= 3 and parts[0] == "TRX":
            transaction_id = "_".join(parts[:3])

    return {
        "file_name": file_path.name if file_path else None,
        "transaction_id": transaction_id,
        "invoice_number": invoice_number,
        "purchase_order_number": po_reference,
        "vendor": {"name": vendor_name, "address": ""},
        "vendor_name": vendor_name,
        "invoice_date": invoice_date,
        "currency": "USD",
        "items": items,
        "subtotal": subtotal,
        "total_discount": discount,
        "shipping": shipping,
        "total_tax": total_tax,
        "total": total,
    }


def extract_mock_receipt(text: str, file_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Parses a mock delivery receipt text document.
    """
    receipt_number = _clean_id(_extract_field(r"Receipt Number:\s*([^\r\n]+)", text))
    delivery_date = _extract_field(r"(?:Delivery\s+)?Date:\s*([0-9\-]+)", text)
    po_reference = _clean_id(_extract_field(r"PO Reference:\s*([^\r\n]+)", text))
    transaction_id = _extract_field(r"Transaction ID:\s*([A-Za-z0-9\_]+)", text)
    if not transaction_id and file_path:
        parts = file_path.stem.split("_")
        if len(parts) >= 3 and parts[0] == "TRX":
            transaction_id = "_".join(parts[:3])

    # Vendor extraction
    vendor_match = re.search(r"(?:VENDOR|SUPPLIER):\s*(.+)", text, re.IGNORECASE)
    vendor_name = vendor_match.group(1).splitlines()[0].strip() if vendor_match else None

    # Line items
    items: List[Dict[str, Any]] = []
    lines = text.splitlines()
    table_started = False

    for line in lines:
        line_s = line.strip()
        if re.search(r"^SKU\b", line_s, re.IGNORECASE) and ("DESCRIPTION" in line_s or "ITEM" in line_s):
            table_started = True
            continue
        if table_started:
            if re.search(r"^(Status|Notes|Note:|Receiver|Received By)", line_s, re.IGNORECASE):
                break
            if line_s.startswith("---") or line_s.startswith("===") or not line_s:
                continue

            # Check for format with QTY ORDERED, QTY DELIVERED, UNIT PRICE, and TOTAL
            m_ord_del_price_tot = re.search(r"^\s*([A-Za-z0-9\-]+)\s+(.+?)\s*(\d+)\s+(\d+)\s+[\$]?([0-9,]+\.\d{2})\s+[\$]?([0-9,]+\.\d{2})\s*$", line_s)
            if m_ord_del_price_tot:
                q_ord = _to_decimal(m_ord_del_price_tot.group(3))
                q_del = _to_decimal(m_ord_del_price_tot.group(4))
                items.append({
                    "item_code": m_ord_del_price_tot.group(1).strip(),
                    "description": m_ord_del_price_tot.group(2).strip(),
                    "quantity_ordered": q_ord,
                    "quantity": q_del,
                    "unit_price": _to_decimal(m_ord_del_price_tot.group(5)),
                    "total": _to_decimal(m_ord_del_price_tot.group(6)),
                })
                continue

            # Check for format with QTY ORDERED, QTY DELIVERED, and TOTAL (e.g. TRX_100_001_doc_3.txt)
            m_ord_del_tot = re.search(r"^\s*([A-Za-z0-9\-]+)\s+(.+?)\s*(\d+)\s+(\d+)\s+[\$]?([0-9,]+\.\d{2})\s*$", line_s)
            if m_ord_del_tot:
                q_ord = _to_decimal(m_ord_del_tot.group(3))
                q_del = _to_decimal(m_ord_del_tot.group(4))
                tot = _to_decimal(m_ord_del_tot.group(5))
                unit_p = (tot / q_del).quantize(Decimal("0.01")) if (q_del and q_del > Decimal("0") and tot is not None) else None
                items.append({
                    "item_code": m_ord_del_tot.group(1).strip(),
                    "description": m_ord_del_tot.group(2).strip(),
                    "quantity_ordered": q_ord,
                    "quantity": q_del,
                    "unit_price": unit_p,
                    "total": tot,
                })
                continue

            # Check for standard invoice/receipt line format with unit price and total: SKU DESC QTY PRICE TOTAL
            m_priced = re.search(r"^\s*([A-Za-z0-9\-]+)\s+(.+?)\s*(\d+)\s+[\$]?([0-9,]+\.\d{2})\s+[\$]?([0-9,]+\.\d{2})\s*$", line_s)
            if m_priced:
                items.append({
                    "item_code": m_priced.group(1).strip(),
                    "description": m_priced.group(2).strip(),
                    "quantity": _to_decimal(m_priced.group(3)),
                    "unit_price": _to_decimal(m_priced.group(4)),
                    "total": _to_decimal(m_priced.group(5)),
                })
                continue

            # Multi-space / tab column splitting
            parts = re.split(r'\s{2,}|\t+', line_s)
            if len(parts) >= 4:
                sku = parts[0].strip()
                desc = parts[1].strip()
                q_ord = re.findall(r'\d+', parts[2])
                q_del = re.findall(r'\d+', parts[3])
                # Check if 4th part is a price rather than quantity
                if '$' in parts[3] or re.match(r'^\d+\.\d{2}$', parts[3].strip()):
                    p_val = _to_decimal(parts[3])
                    tot_val = _to_decimal(parts[4]) if len(parts) >= 5 else None
                    q_val = _to_decimal(q_ord[0]) if q_ord else Decimal("1")
                    items.append({
                        "item_code": sku,
                        "description": desc,
                        "quantity": q_val,
                        "unit_price": p_val,
                        "total": tot_val or (q_val * p_val if (q_val and p_val) else None),
                    })
                elif q_ord and q_del:
                    q_del_dec = _to_decimal(q_del[0])
                    q_ord_dec = _to_decimal(q_ord[0])
                    p_val = None
                    tot_val = None
                    if len(parts) >= 6 and ('$' in parts[4] or re.search(r'\d+\.\d{2}', parts[4])) and ('$' in parts[5] or re.search(r'\d+\.\d{2}', parts[5])):
                        p_val = _to_decimal(parts[4])
                        tot_val = _to_decimal(parts[5])
                    elif len(parts) >= 5 and ('$' in parts[4] or re.search(r'\d+\.\d{2}', parts[4])):
                        tot_val = _to_decimal(parts[4])
                        if q_del_dec and q_del_dec > Decimal("0") and tot_val is not None:
                            p_val = (tot_val / q_del_dec).quantize(Decimal("0.01"))

                    item_dict = {
                        "item_code": sku,
                        "description": desc,
                        "quantity_ordered": q_ord_dec,
                        "quantity": q_del_dec,
                    }
                    if p_val is not None:
                        item_dict["unit_price"] = p_val
                    if tot_val is not None:
                        item_dict["total"] = tot_val
                    items.append(item_dict)
            elif len(parts) >= 2:
                first = parts[0].strip()
                last_num_match = re.findall(r'\d+', parts[-1])
                q_del = last_num_match[0] if last_num_match else "0"

                # Check if first part has SKU and description
                m_first = re.match(r'^([A-Za-z0-9\-]+)\s+(.*?)(?:\s*(\d+))?$', first)
                if m_first:
                    sku = m_first.group(1)
                    desc = m_first.group(2)
                    q_ord = m_first.group(3) or q_del
                    items.append({
                        "item_code": sku,
                        "description": desc,
                        "quantity_ordered": _to_decimal(q_ord),
                        "quantity": _to_decimal(q_del),
                    })

    subtotal = _to_decimal(_extract_field(r"SUBTOTAL\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text))
    discount = _to_decimal(_extract_field(r"DISCOUNT\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text)) or Decimal("0.00")
    shipping = _to_decimal(_extract_field(r"SHIPPING(?: & HANDLING)?\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text)) or Decimal("0.00")
    total_tax = _to_decimal(_extract_field(r"TAX.*?\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text)) or Decimal("0.00")
    total = _to_decimal(_extract_field(r"\b(?:GRAND TOTAL|TOTAL DUE|TOTAL|AMOUNT PAID|AMOUNT DUE)\b\s*[:\s]\s*[\$]?([0-9,]+\.\d{2})", text))

    return {
        "file_name": file_path.name if file_path else None,
        "transaction_id": transaction_id,
        "receipt_number": receipt_number,
        "purchase_order_number": po_reference,
        "vendor_name": vendor_name,
        "date": delivery_date,
        "currency": "USD",
        "subtotal": subtotal,
        "total_discount": discount,
        "shipping": shipping,
        "total_tax": total_tax,
        "total": total,
        "items": items,
    }

