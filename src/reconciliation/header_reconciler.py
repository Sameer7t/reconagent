import sys
import re
import logging
from typing import Optional, Tuple, List, Dict, Any
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas.reconciliation import (
    Discrepancy,
    DiscrepancyType,
    Severity,
    ReconciliationCheck,
    ReconciliationPolicy
)
from reconciliation.document_linker import normalize_po_number

logger = logging.getLogger(__name__)

def normalize_vendor_name(name: Optional[str]) -> Optional[str]:
    """
    Normalizes a vendor name by lowercasing, stripping corporate suffixes,
    removing punctuation, and collapsing whitespace.
    """
    if not name:
        return None
    
    name = name.lower()
    
    # Strip corporate suffixes
    suffixes = [
        r'\bltd\b', r'\blimited\b', r'\binc\b', r'\bincorporated\b', r'\bllc\b',
        r'\bcorp\b', r'\bcorporation\b', r'\bco\b', r'\bcompany\b', r'\bgroup\b',
        r'\bholdings\b', r'\bpty\b', r'\bpvt\b', r'\bsa\b', r'\bgmbh\b',
        r'\bag\b', r'\bplc\b', r'\blp\b', r'\bllp\b'
    ]
    for suffix in suffixes:
        name = re.sub(suffix, '', name)
        
    # Remove periods, commas, dashes
    name = re.sub(r'[\.,\-]', ' ', name)
    
    # Collapse whitespace and strip
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name if name else None


def normalize_currency_code(currency: Optional[str]) -> Optional[str]:
    """
    Normalizes a currency code or symbol to a standard 3-letter currency code.
    """
    if not currency:
        return None
        
    currency = currency.strip()
    if not currency:
        return None
        
    symbol_map = {
        '$': 'USD',
        'US$': 'USD',
        'USD$': 'USD',
        'CAD$': 'CAD',
        'CAN$': 'CAD',
        'CA$': 'CAD',
        'A$': 'AUD',
        'AU$': 'AUD',
        'NZ$': 'NZD',
        '€': 'EUR',
        '£': 'GBP',
        '¥': 'JPY',
        '₹': 'INR',
        'RS': 'PKR',
        'RS.': 'PKR',
        'PKR': 'PKR',
        'INR': 'INR',
        'RM': 'MYR',
        'R': 'ZAR'
    }
    
    if currency in symbol_map:
        return symbol_map[currency]
    upper_c = currency.upper()
    if upper_c in symbol_map:
        return symbol_map[upper_c]
        
    return upper_c


def reconcile_headers(
    po_data: Dict[str, Any],
    invoice_data: Optional[Dict[str, Any]] = None,
    receipt_data_list: Optional[List[Dict[str, Any]]] = None,
    policy: Optional[ReconciliationPolicy] = None
) -> Tuple[List[ReconciliationCheck], List[Discrepancy]]:
    """
    Performs header-level reconciliation across PO, Invoice, and Receipts.
    
    Checks performed:
    1. Vendor Alignment Check
    2. PO Reference Check
    3. Currency Parity Check
    """
    logger.info("Starting header reconciliation")
    
    invoice_data = invoice_data or {}
    receipt_data_list = receipt_data_list or []
    
    checks = []
    discrepancies = []
    
    po_id = po_data.get('purchase_order_number') or po_data.get('id', 'Unknown PO')
    inv_id = invoice_data.get('invoice_number') or invoice_data.get('id', 'Unknown Invoice')
    
    # --- A. Vendor Alignment Check ---
    vendor_passed = True
    vendor_details = []
    
    po_vendor = po_data.get('vendor_name')
    norm_po_vendor = normalize_vendor_name(po_vendor)
    
    inv_vendor_obj = invoice_data.get('vendor')
    inv_vendor = inv_vendor_obj.get('name') if isinstance(inv_vendor_obj, dict) else None
    norm_inv_vendor = normalize_vendor_name(inv_vendor)
    
    if invoice_data and norm_po_vendor and norm_inv_vendor and norm_po_vendor != norm_inv_vendor:
        vendor_passed = False
        msg = f"Vendor mismatch between PO ({po_vendor}) and Invoice ({inv_vendor})"
        vendor_details.append(msg)
        discrepancies.append(Discrepancy(
            type=DiscrepancyType.VENDOR_MISMATCH,
            severity=Severity.CRITICAL,
            document_ids=[po_id, inv_id],
            expected_value=po_vendor,
            actual_value=inv_vendor,
            explanation=msg
        ))
        
    for rec in receipt_data_list:
        rec_id = rec.get('receipt_number') or rec.get('id', 'Unknown Receipt')
        rec_vendor = rec.get('vendor_name')
        norm_rec_vendor = normalize_vendor_name(rec_vendor)
        if norm_po_vendor and norm_rec_vendor and norm_po_vendor != norm_rec_vendor:
            vendor_passed = False
            msg = f"Vendor mismatch between PO ({po_vendor}) and Receipt ({rec_vendor})"
            vendor_details.append(msg)
            discrepancies.append(Discrepancy(
                type=DiscrepancyType.VENDOR_MISMATCH,
                severity=Severity.CRITICAL,
                document_ids=[po_id, rec_id],
                expected_value=po_vendor,
                actual_value=rec_vendor,
                explanation=msg
            ))
            
    checks.append(ReconciliationCheck(
        check_name='vendor_alignment',
        stage='header',
        passed=vendor_passed,
        details={"info": "; ".join(vendor_details)} if vendor_details else {},
        message="; ".join(vendor_details) if vendor_details else "Vendor names align"
    ))
    
    # --- B. PO Reference Check ---
    po_ref_passed = True
    po_ref_details = []
    
    po_number = po_data.get('purchase_order_number')
    inv_po_number = invoice_data.get('purchase_order_number')
    norm_po_num = normalize_po_number(po_number)
    norm_inv_po = normalize_po_number(inv_po_number)
    
    if invoice_data and inv_po_number and po_number:
        if str(inv_po_number).strip() != str(po_number).strip() and (not norm_po_num or norm_inv_po != norm_po_num):
            po_ref_passed = False
            msg = f"PO reference mismatch: Expected {po_number}, got {inv_po_number} on Invoice"
            po_ref_details.append(msg)
            discrepancies.append(Discrepancy(
                type=DiscrepancyType.DOCUMENT_LINK_MISMATCH,
                severity=Severity.CRITICAL,
                document_ids=[po_id, inv_id],
                expected_value=str(po_number),
                actual_value=str(inv_po_number),
                explanation=msg
            ))
        
    for rec in receipt_data_list:
        rec_id = rec.get('receipt_number') or rec.get('id', 'Unknown Receipt')
        rec_po_number = rec.get('purchase_order_number')
        norm_rec_po = normalize_po_number(rec_po_number)
        if rec_po_number and po_number:
            if str(rec_po_number).strip() != str(po_number).strip() and (not norm_po_num or norm_rec_po != norm_po_num):
                po_ref_passed = False
                msg = f"PO reference mismatch: Expected {po_number}, got {rec_po_number} on Receipt"
                po_ref_details.append(msg)
                discrepancies.append(Discrepancy(
                    type=DiscrepancyType.DOCUMENT_LINK_MISMATCH,
                    severity=Severity.CRITICAL,
                    document_ids=[po_id, rec_id],
                    expected_value=str(po_number),
                    actual_value=str(rec_po_number),
                    explanation=msg
                ))
            
    checks.append(ReconciliationCheck(
        check_name='po_reference',
        stage='header',
        passed=po_ref_passed,
        details={"info": "; ".join(po_ref_details)} if po_ref_details else {},
        message="; ".join(po_ref_details) if po_ref_details else "PO references align"
    ))
    
    # --- C. Currency Check ---
    currency_passed = True
    currency_details = []
    
    po_currency = normalize_currency_code(po_data.get('currency'))
    inv_currency = normalize_currency_code(invoice_data.get('currency'))
    
    if invoice_data and po_currency and inv_currency and po_currency != inv_currency:
        currency_passed = False
        msg = f"Currency mismatch: PO has {po_currency}, Invoice has {inv_currency}"
        currency_details.append(msg)
        discrepancies.append(Discrepancy(
            type=DiscrepancyType.CURRENCY_MISMATCH,
            severity=Severity.CRITICAL,
            document_ids=[po_id, inv_id],
            expected_value=po_currency,
            actual_value=inv_currency,
            explanation=msg
        ))
        
    for rec in receipt_data_list:
        rec_id = rec.get('receipt_number') or rec.get('id', 'Unknown Receipt')
        rec_currency = normalize_currency_code(rec.get('currency'))
        if po_currency and rec_currency and po_currency != rec_currency:
            currency_passed = False
            msg = f"Currency mismatch: PO has {po_currency}, Receipt has {rec_currency}"
            currency_details.append(msg)
            discrepancies.append(Discrepancy(
                type=DiscrepancyType.CURRENCY_MISMATCH,
                severity=Severity.CRITICAL,
                document_ids=[po_id, rec_id],
                expected_value=po_currency,
                actual_value=rec_currency,
                explanation=msg
            ))
            
    checks.append(ReconciliationCheck(
        check_name='currency_parity',
        stage='header',
        passed=currency_passed,
        details={"info": "; ".join(currency_details)} if currency_details else {},
        message="; ".join(currency_details) if currency_details else "Currencies align"
    ))
    
    logger.info(f"Header reconciliation completed. Found {len(discrepancies)} discrepancies.")
    return checks, discrepancies
